import asyncio
import re
import uuid
import pandas as pd
from typing import Any, List as ListType
from pathlib import Path
from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.engine import URL
from src.agents.agent import Agent
from src.common.credentials import CredentialStorage
from src.agents.tools.df_to_text_converter import DataFrameToTextConverter
from src.agents.tools.init_tools import (
    follow_up,
    generate_sql_query,
    initialize_components,
    show_table,
    # Import custom exceptions
    ToolException,
    VectorSearchException,
    SQLGenerationException,
    SQLExecutionException,
    NoRelevantTablesException,
    InvalidSQLException,
    DataConversionException,
    MissingContextException,
)
from src.agents.tools.required_tables_searcher import VectorStore
from src.agents.tools.sql_creator import SQLCreator
from src.agents.tools.sql_executor import SQLExecutor
from src.agents.tools.controller import SQLController
from src.common.dto import Message
from src.common.exceptions import (
    AIServiceError,
    BaseServiceError,
    ConfigurationError,
    DatabaseError,
)
from src.common.logger import get_logger
from src.common.settings import Settings
from src.llm.utils import create_llm_from_settings

logger = get_logger(__name__)

TOOLS = [generate_sql_query, show_table, follow_up]


class MessageService:
    def __init__(
        self,
        settings: Settings,
        scanner_service: Any = None,
        metadata_engine: AsyncEngine | None = None,
        embedding_service: Any = None,
    ):
        self.settings = settings
        self._agent: Agent | None = None
        self._engine: AsyncEngine | None = None
        self._initialized_connection_id: str | None = None
        self._init_lock = asyncio.Lock()
        self._scanner_service = scanner_service
        self._metadata_engine = metadata_engine
        self._embedding_service = embedding_service

    def _load_table_descriptions(self) -> pd.DataFrame:
        data_path = (
            Path(__file__).resolve().parents[2] / "data" / "full_desc_table_v2.csv"
        )
        if not data_path.exists():
            raise ConfigurationError(f"Table descriptions file not found: {data_path}")
        return pd.read_csv(data_path)

    async def close(self) -> None:
        """Dispose of the cached database engine, if any."""
        if self._engine is not None:
            try:
                await self._engine.dispose()
            except Exception as e:
                logger.warning(f"Failed to dispose engine: {e}")
            self._engine = None
            self._initialized_connection_id = None
            self._agent = None

    async def _initialize_agent(self) -> None:
        # Fast path: already initialized for the currently active connection.
        active_connection_id = self._get_active_connection_id()
        if (
            self._agent is not None
            and self._initialized_connection_id == active_connection_id
        ):
            return

        async with self._init_lock:
            # Re-check under the lock in case another coroutine beat us to it.
            active_connection_id = self._get_active_connection_id()
            if (
                self._agent is not None
                and self._initialized_connection_id == active_connection_id
            ):
                return

            # Active connection changed: dispose of the old engine before rebuilding.
            if self._engine is not None:
                try:
                    await self._engine.dispose()
                except Exception as e:
                    logger.warning(f"Failed to dispose previous engine: {e}")
                self._engine = None

            await self._build_agent()

    def _get_active_connection_id(self) -> str:
        if not self.settings.credential_encryption_key:
            raise ConfigurationError("CREDENTIAL_ENCRYPTION_KEY not configured.")
        storage = CredentialStorage(
            self.settings.credential_storage_path,
            self.settings.credential_encryption_key,
        )
        active = storage.get_active_connection()
        if not active or not active.id:
            raise ConfigurationError(
                "No active database connection. Please activate a connection first."
            )
        return active.id

    async def _seed_follow_up_context(self, messages: list[Message]) -> None:
        """Pre-populate the follow_up tool's table cache from prior turns.

        ContextVars don't survive across HTTP requests, so on each request
        we re-derive the relevant tables for the most recent user→assistant
        SQL exchange and seed the cache.
        """
        from src.agents.tools.init_tools import (
            _vector_store,
            set_last_tables,
        )

        if _vector_store is None or len(messages) < 2:
            return

        # Find the most recent prior user message whose assistant reply had SQL.
        prior_user_query: str | None = None
        for i in range(len(messages) - 2, -1, -1):
            msg = messages[i]
            if msg.role != "user":
                continue
            if i + 1 < len(messages):
                next_msg = messages[i + 1]
                if next_msg.role == "assistant" and (
                    next_msg.sql_query or next_msg.type in ("sql", "text_with_csv")
                ):
                    prior_user_query = msg.content
                    break

        if not prior_user_query:
            return

        try:
            tables = await _vector_store.search(query_text=prior_user_query, limit=14)
            if tables:
                set_last_tables(tables)
                logger.info(
                    f"Seeded follow-up cache with {len(tables)} tables "
                    f"from prior query: {prior_user_query[:80]!r}"
                )
        except Exception as e:
            logger.warning(f"Failed to seed follow-up cache: {e}")

    async def _ensure_embeddings_ready(self, connection_id: str) -> None:
        """Trigger an initial scan if no embeddings exist yet for this
        connection. The metadata DB always has the `notes` table — only
        per-connection rows might be missing."""
        if self._embedding_service is None or self._scanner_service is None:
            return

        count = await self._embedding_service.count_embeddings(connection_id)
        if count > 0:
            return

        logger.info(
            f"No embeddings for {connection_id} in metadata DB; "
            f"running initial scan"
        )
        await self._scanner_service.scan_connection(connection_id)

    async def _build_agent(self) -> None:
        logger.info("Initializing AI agent components")
        logger.info(f"Using LLM provider: {self.settings.llm_provider}")
        logger.info(f"Using model: {self.settings.model_id}")

        try:
            base_llm = create_llm_from_settings(
                self.settings,
                for_agent=True,
            )
            logger.info(f"LLM client created successfully: {type(base_llm).__name__}")
        except ValueError as e:
            raise ConfigurationError(str(e))
        except PydanticValidationError as e:
            if "Could not authenticate" in str(e):
                raise ConfigurationError(f"LLM provider authentication failed: {e}")
            raise ConfigurationError(f"Invalid LLM configuration: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize LLM client: {e}")

        # Get the active connection from storage to use its database details
        try:
            if not self.settings.credential_encryption_key:
                raise ConfigurationError("CREDENTIAL_ENCRYPTION_KEY not configured.")
            storage = CredentialStorage(
                self.settings.credential_storage_path,
                self.settings.credential_encryption_key,
            )
            active_connection = storage.get_active_connection()
            if not active_connection:
                raise ConfigurationError("No active database connection. Please activate a connection first.")

            active_connection_id = active_connection.id
            logger.info(f"Using active connection: {active_connection_id}")
        except ConfigurationError:
            raise
        except Exception as e:
            raise ConfigurationError(f"Failed to get active connection: {e}")

        try:
            logger.info("Creating database URL object")
            logger.info(
                f"Database settings: host={active_connection.host}, port={active_connection.port}, database={active_connection.database}, username={active_connection.username}"
            )

            url = URL.create(
                "postgresql+asyncpg",
                username=active_connection.username,
                password=active_connection.password,
                host=active_connection.host,
                port=active_connection.port,
                database=active_connection.database,
            )
            logger.info(
                f"Database URL created: {str(url).replace(active_connection.password, '***')}"
            )

            logger.info("Creating async engine with connection parameters")
            logger.info(
                "Engine config: pool_pre_ping=True, pool_size=5, max_overflow=10, pool_recycle=3600"
            )

            engine = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                pool_recycle=3600,
                echo=False,
                # asyncpg connection parameters
                connect_args={
                    "command_timeout": 900,  # 15 minutes timeout for asyncpg
                },
            )
            logger.info(f"Async engine created successfully: {engine}")
            logger.info(f"Engine pool info: {engine.pool}")

        except Exception as e:
            logger.error(f"Failed to create database engine: {e}")
            logger.exception("Database engine creation traceback:")
            raise DatabaseError(f"Failed to create database connection: {e}")

        try:
            desc_data = await asyncio.to_thread(self._load_table_descriptions)
        except FileNotFoundError as e:
            raise ConfigurationError(f"Missing required data files: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load table descriptions: {e}")

        try:
            # Lazy-initialize embeddings if no rows exist yet for this
            # connection. This guarantees the agent works on first chat
            # even when the background scanner is disabled.
            try:
                await self._ensure_embeddings_ready(active_connection_id)
            except Exception as e:
                logger.warning(f"Could not ensure embeddings ready: {e}")

            if self._metadata_engine is None:
                raise ConfigurationError(
                    "MessageService initialized without a metadata engine. "
                    "The lifespan must wire MetadataDB.engine in."
                )

            vector_store = VectorStore(
                engine=self._metadata_engine,
                chat_model=base_llm,
                connection_id=active_connection_id,
                default_model="multilingual-e5-small",
            )

            sql_creator = SQLCreator(
                chat_model=base_llm,
                desc_data=desc_data,
            )

            executor = SQLExecutor(engine=engine)
            df_to_text = DataFrameToTextConverter(chat_model=base_llm)
            sql_controller = SQLController(chat_model=base_llm)

            initialize_components(
                chat_model=base_llm,
                vector_store=vector_store,
                sql_creator=sql_creator,
                sql_controller=sql_controller,
                executor=executor,
                df_to_text=df_to_text,
            )

            self._agent = Agent(base_llm, TOOLS, tool_choice_required=False)
            self._engine = engine
            self._initialized_connection_id = active_connection_id

            logger.info("AI agent initialized successfully")

        except Exception as e:
            raise AIServiceError(f"Failed to initialize agent components: {e}")

    def _convert_messages_to_langchain(
        self, messages: list[Message]
    ) -> ListType[BaseMessage]:
        langchain_messages = []
        for msg in messages:
            if msg.role == "user":
                langchain_messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                langchain_messages.append(AIMessage(content=msg.content))
        return langchain_messages

    def _convert_agent_response_to_message(self, response: dict[str, Any]) -> Message:
        logger.info("Converting agent response to message format")
        logger.info(f"Response keys: {list(response.keys())}")
        logger.info(f"Response values preview: {str(response)[:500]}...")

        message_type = "plain"
        download_link = None
        sql_query = None
        preview_data = None
        content = ""

        response_type = response.get("type")
        logger.info(f"Response type from agent: {response_type}")

        if response_type == "sql":
            logger.info("Processing SQL response type")
            message_type = "sql"
            content = response.get("sql", "")
            logger.info(f"SQL content length: {len(content)}")

            # Handle case where SQL is generated but content is empty
            if not content or not content.strip():
                logger.warning("SQL response has empty content")
                message_type = "plain"
                content = ("I couldn't generate a valid SQL query for your question. "
                          "Please try rephrasing your question with more specific details "
                          "or different keywords.")
        elif response_type == "text_with_csv":
            logger.info("Processing text_with_csv response type")
            message_type = "text_with_csv"

            # Extract SQL query and preview data
            sql_query = response.get("sql_query")
            preview_data = response.get("preview_data")

            # Build content message
            content_parts = []
            if sql_query:
                content_parts.append(f"**Generated SQL Query:**\n```sql\n{sql_query}\n```\n")
                logger.info(f"SQL query length: {len(sql_query)}")

            if preview_data:
                content_parts.append(f"**Results Preview (first 10 rows):**\n{preview_data}\n")
                logger.info(f"Preview data length: {len(preview_data)}")

            content_parts.append("Full results are available for download.")
            content = "\n".join(content_parts)

            download_links = response.get("download_link", {})
            logger.info(f"Download links: {download_links}")
            if isinstance(download_links, dict) and "csv" in download_links:
                # Extract just the filename from the URL if it's already a full URL
                csv_file = download_links["csv"]
                if csv_file.startswith("http"):
                    # Already a full URL, use as-is
                    download_link = csv_file
                else:
                    # Just a filename, construct the full URL
                    download_link = f"{self.settings.csv_download_base_url}/{csv_file}"
                logger.info(f"CSV download link: {download_link}")
        else:
            logger.info(f"Processing default/text response type: {response_type}")
            content = response.get("content", "")
            logger.info(f"Content length: {len(content)}")

            # Check if SQL was included in the response (from generate_sql_query)
            if response.get("sql"):
                sql_query = response.get("sql")
                logger.info(f"SQL query included in response, length: {len(sql_query)}")

        error = response.get("error")
        if error:
            logger.warning(f"Response contains error: {error}")
            content = f"I encountered an issue: {error}"

        result = Message(
            role="assistant",
            content=content,
            type=message_type,
            download_link=download_link,
            sql_query=sql_query,
            preview_data=preview_data,
        )

        logger.info(
            f"Converted message: role={result.role}, type={result.type}, content_len={len(result.content)}, has_download_link={result.download_link is not None}, has_sql={sql_query is not None}, has_preview={preview_data is not None}"
        )
        return result

    async def process_messages(self, messages: list[Message]) -> Message:
        import time

        start_time = time.time()
        logger.info(f"Starting process_messages with {len(messages)} messages")

        if not messages:
            logger.info("No messages provided, returning default response")
            return Message(
                role="assistant",
                content="Please send me a message to get started.",
                type="plain",
            )

        try:
            # Log message details
            for i, msg in enumerate(messages):
                logger.info(
                    f"Message {i + 1}: role={msg.role}, type={msg.type}, content_length={len(msg.content)}"
                )

            logger.info("Starting agent initialization")
            init_start = time.time()
            await self._initialize_agent()
            init_time = time.time() - init_start
            logger.info(f"Agent initialization completed in {init_time:.2f}s")

            if not self._agent:
                logger.error("Agent is None after initialization")
                raise AIServiceError("Agent failed to initialize")

            logger.info("Converting messages to langchain format")
            langchain_messages = self._convert_messages_to_langchain(messages)
            logger.info(
                f"Converted {len(langchain_messages)} messages to langchain format"
            )

            # Seed the follow-up table cache from prior turns so the agent's
            # follow_up tool finds context. ContextVars don't persist across
            # HTTP requests (each request runs in a fresh task), so we
            # re-derive the relevant tables by searching with the previous
            # user query that produced SQL.
            await self._seed_follow_up_context(messages)

            logger.info("Starting agent chat processing")
            chat_start = time.time()
            response = await self._agent.chat(langchain_messages)
            chat_time = time.time() - chat_start
            logger.info(f"Agent chat completed in {chat_time:.2f}s")

            logger.info(f"Raw agent response type: {type(response)}")
            logger.info(
                f"Raw agent response keys: {response.keys() if isinstance(response, dict) else 'Not a dict'}"
            )

            logger.info("Converting agent response to message format")
            result_message = self._convert_agent_response_to_message(response)

            total_time = time.time() - start_time
            logger.info(f"process_messages completed successfully in {total_time:.2f}s")
            logger.info(
                f"Final response: role={result_message.role}, type={result_message.type}, content_length={len(result_message.content)}"
            )

            return result_message

        except NoRelevantTablesException as e:
            logger.warning(f"No relevant tables found: {e}")
            error_response = Message(
                role="assistant",
                content=str(e),
                type="plain",
            )
            return error_response
        except MissingContextException as e:
            logger.warning(f"Missing context for follow-up: {e}")
            error_response = Message(
                role="assistant",
                content=str(e),
                type="plain",
            )
            return error_response
        except InvalidSQLException as e:
            logger.warning(f"Invalid SQL generated: {e}")
            error_response = Message(
                role="assistant",
                content=str(e),
                type="plain",
            )
            return error_response
        except VectorSearchException as e:
            logger.error(f"Vector search failed: {e}")
            error_response = Message(
                role="assistant",
                content="I'm having trouble searching for relevant data tables. Please try again in a moment.",
                type="plain",
            )
            return error_response
        except SQLGenerationException as e:
            logger.error(f"SQL generation failed: {e}")
            error_response = Message(
                role="assistant",
                content="I couldn't generate a SQL query for your question. Please try rephrasing with more specific details.",
                type="plain",
            )
            return error_response
        except SQLExecutionException as e:
            logger.error(f"SQL execution failed: {e}")
            error_msg = str(e).lower()
            if 'timeout' in error_msg:
                user_message = "The query took too long to execute. Please try a simpler question or narrow your search criteria."
            elif 'syntax' in error_msg:
                user_message = "There was an issue with the generated query. Please try rephrasing your question."
            elif 'permission' in error_msg:
                user_message = "I don't have permission to access the requested data. Please contact your administrator."
            else:
                user_message = "I encountered an issue executing the database query. Please try again or rephrase your question."

            error_response = Message(
                role="assistant",
                content=user_message,
                type="plain",
            )
            return error_response
        except DataConversionException as e:
            logger.error(f"Data conversion failed: {e}")
            error_response = Message(
                role="assistant",
                content="I had trouble formatting the results. Please try a simpler query.",
                type="plain",
            )
            return error_response
        except ToolException as e:
            logger.error(f"Tool exception: {e}")
            error_response = Message(
                role="assistant",
                content="I encountered an issue while processing your request. Please try again.",
                type="plain",
            )
            return error_response
        except BaseServiceError as e:
            logger.error(f"Service error processing messages: {e}")
            logger.error(f"Service error type: {type(e)}")
            logger.error(f"Service error code: {e.error_code}")
            error_response = Message(
                role="assistant",
                content=e.user_message,
                type="plain",
            )
            logger.info(f"Returning service error response: {error_response}")
            return error_response
        except Exception as e:
            logger.error(f"Unexpected error processing messages: {e}")
            logger.error(f"Unexpected error type: {type(e)}")
            logger.exception("Full traceback for unexpected error:")
            error_response = Message(
                role="assistant",
                content="I'm experiencing technical difficulties. Please try again later.",
                type="plain",
            )
            logger.info(f"Returning unexpected error response: {error_response}")
            return error_response


class SqlService:
    READ_ONLY_DENYLIST = re.compile(
        r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|MERGE|CREATE\s+TABLE|CREATE\s+INDEX)\b",
        re.IGNORECASE,
    )

    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = get_logger(__name__)

    def _validate_sql(self, sql: str) -> None:
        self.logger.info("=== SQL Validation START ===")
        self.logger.info(f"Validating SQL query: {sql}")
        self.logger.info(f"Using regex pattern: {self.READ_ONLY_DENYLIST.pattern}")

        match = self.READ_ONLY_DENYLIST.search(sql)
        if match:
            self.logger.warning(
                f"SQL validation failed - found forbidden operation: {match.group()}"
            )
            self.logger.warning(f"Match position: {match.start()}-{match.end()}")
            raise ValueError(
                "Only SELECT queries are allowed. Modification operations (DROP, DELETE, UPDATE, INSERT, ALTER, etc.) are forbidden."
            )

        self.logger.info("=== SQL Validation SUCCESS ===")

    def _generate_csv_file(self, df: pd.DataFrame) -> str | None:
        from time import perf_counter

        csv_start_time = perf_counter()
        self.logger.info("=== CSV Generation START ===")
        self.logger.info(f"DataFrame shape: {df.shape}")

        try:
            path_creation_start = perf_counter()
            csv_export_path = Path(self.settings.csv_export_path)
            self.logger.info(f"CSV export path: {csv_export_path}")

            csv_export_path.mkdir(parents=True, exist_ok=True)
            path_creation_time = perf_counter() - path_creation_start
            self.logger.info(
                f"Directory creation completed in {path_creation_time:.3f}s"
            )

            filename_start = perf_counter()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"query_results_{timestamp}_{unique_id}.csv"
            csv_file_path = csv_export_path / filename
            filename_time = perf_counter() - filename_start
            self.logger.info(f"Filename generated in {filename_time:.3f}s: {filename}")

            write_start = perf_counter()
            df.to_csv(csv_file_path, index=False)
            write_time = perf_counter() - write_start
            self.logger.info(f"CSV file written in {write_time:.3f}s")

            file_stats_start = perf_counter()
            file_size = csv_file_path.stat().st_size
            file_stats_time = perf_counter() - file_stats_start
            self.logger.info(
                f"File stats retrieved in {file_stats_time:.3f}s - size: {file_size} bytes"
            )

            # Return the full URL for the download link
            download_link = f"{self.settings.csv_download_base_url}/{filename}"
            total_csv_time = perf_counter() - csv_start_time
            self.logger.info(f"=== CSV Generation SUCCESS in {total_csv_time:.3f}s ===")
            self.logger.info(f"CSV file generated: {csv_file_path}")
            self.logger.info(f"Download link: {download_link}")

            return download_link

        except Exception as e:
            error_time = perf_counter() - csv_start_time
            self.logger.error(f"=== CSV Generation ERROR after {error_time:.3f}s ===")
            self.logger.error(f"CSV generation error type: {type(e)}")
            self.logger.error(f"CSV generation error message: {str(e)}")
            self.logger.exception("Full CSV generation error traceback:")
            return None

    async def execute_sql(self, sql: str) -> Message:
        from time import perf_counter

        start_time = perf_counter()
        self.logger.info("=== SqlService.execute_sql START ===")
        self.logger.info(f"Received SQL query of length {len(sql)}")
        self.logger.info(f"SQL query: {sql}")

        validation_start = perf_counter()
        self.logger.info("Starting SQL validation")
        try:
            self._validate_sql(sql)
            validation_time = perf_counter() - validation_start
            self.logger.info(f"SQL validation passed in {validation_time:.3f}s")
        except ValueError as e:
            validation_time = perf_counter() - validation_start
            self.logger.warning(
                f"SQL validation failed in {validation_time:.3f}s: {str(e)}"
            )
            raise

        # Get the active connection from CredentialStorage
        if not self.settings.credential_encryption_key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY not configured.")
        storage = CredentialStorage(
            self.settings.credential_storage_path,
            self.settings.credential_encryption_key,
        )
        active_connection = storage.get_active_connection()
        if not active_connection:
            raise ValueError("No active database connection. Please activate a connection first.")

        self.logger.info(f"Using active connection: {active_connection.id}")

        # Use URL.create so special characters in the password (@ / : # etc.)
        # don't corrupt the DSN.
        db_url = URL.create(
            "postgresql+asyncpg",
            username=active_connection.username,
            password=active_connection.password,
            host=active_connection.host,
            port=active_connection.port,
            database=active_connection.database,
        )
        self.logger.info(
            f"Database URL: postgresql+asyncpg://{active_connection.username}:***@"
            f"{active_connection.host}:{active_connection.port}/{active_connection.database}"
        )

        executor_creation_start = perf_counter()
        executor = SQLExecutor.create_with_url(db_url, echo=self.settings.database_echo)
        self.logger.info(
            f"SQLExecutor created in {perf_counter() - executor_creation_start:.3f}s"
        )

        try:
            query_start = perf_counter()
            self.logger.info("Executing SQL query")
            df = await executor.query(sql)
            query_time = perf_counter() - query_start
            self.logger.info(f"SQL query executed in {query_time:.3f}s")
            self.logger.info(
                f"Query returned {len(df)} rows, {len(df.columns) if not df.empty else 0} columns"
            )

            if not df.empty:
                self.logger.info(f"DataFrame columns: {list(df.columns)}")
                self.logger.info(f"DataFrame dtypes: {df.dtypes.to_dict()}")
                self.logger.info(
                    f"DataFrame memory usage: {df.memory_usage(deep=True).sum()} bytes"
                )

            download_link = None
            preview_data = None
            formatting_start = perf_counter()

            if df.empty:
                content = "Query executed successfully but returned no results."
                self.logger.info("Query returned empty result set")
            else:
                self.logger.info("Formatting query results as markdown table")
                content = f"Query executed successfully. Returned {len(df)} rows."

                # Generate preview (first 10 rows) as markdown
                markdown_start = perf_counter()
                preview_df = df.head(10)
                preview_data = preview_df.to_markdown(index=False)
                markdown_time = perf_counter() - markdown_start
                self.logger.info(
                    f"Markdown preview generated in {markdown_time:.3f}s"
                )

                csv_start = perf_counter()
                self.logger.info("Generating CSV file")
                download_link = self._generate_csv_file(df)
                csv_time = perf_counter() - csv_start
                self.logger.info(f"CSV generation completed in {csv_time:.3f}s")

            formatting_time = perf_counter() - formatting_start
            self.logger.info(f"Result formatting completed in {formatting_time:.3f}s")

            message_creation_start = perf_counter()
            result = Message(
                role="assistant",
                content=content,
                type="text_with_csv",
                download_link=download_link,
                sql_query=sql,
                preview_data=preview_data,
            )
            message_creation_time = perf_counter() - message_creation_start
            self.logger.info(f"Message object created in {message_creation_time:.3f}s")

            total_time = perf_counter() - start_time
            self.logger.info(
                f"=== SqlService.execute_sql SUCCESS in {total_time:.3f}s ==="
            )
            self.logger.info(
                f"Final result - content length: {len(result.content)}, download_link: {result.download_link}"
            )

            return result

        except Exception as e:
            error_time = perf_counter() - start_time
            self.logger.error(
                f"=== SqlService.execute_sql ERROR after {error_time:.3f}s ==="
            )
            self.logger.error(f"Error type: {type(e)}")
            self.logger.error(f"Error message: {str(e)}")
            self.logger.exception("Full SqlService error traceback:")
            raise
        finally:
            cleanup_start = perf_counter()
            self.logger.info("Closing SQLExecutor")
            await executor.close()
            cleanup_time = perf_counter() - cleanup_start
            self.logger.info(f"SQLExecutor closed in {cleanup_time:.3f}s")


__all__ = ["MessageService", "SqlService"]
