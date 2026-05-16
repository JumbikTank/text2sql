import json
from typing import Any, Literal
from json import JSONDecodeError

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from sqlalchemy import text as sqltext
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from sentence_transformers import SentenceTransformer
from pgvector.asyncpg import register_vector
from src.agents.tools.prompt_templates import SYSTEM_FILTER_PROMPT


# Custom exceptions for Vector Store
class VectorStoreException(Exception):
    """Base exception for Vector Store errors"""

    pass


class VectorSearchException(VectorStoreException):
    """Exception raised when vector search fails"""

    pass


class EmbeddingException(VectorStoreException):
    """Exception raised when embedding generation fails"""

    pass


class TableFilterException(VectorStoreException):
    """Exception raised when table filtering fails"""

    pass


class ConnectionException(VectorStoreException):
    """Exception raised when database connection fails"""

    pass


class InitializationException(VectorStoreException):
    """Exception raised when initialization fails"""

    pass


Distance = Literal["COSINE", "DOT", "EUCLIDEAN"]


class VectorStore:
    """Searches the shared `notes` table in the metadata DB scoped to a
    single connection_id."""

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        chat_model: BaseChatModel,
        connection_id: str,
        default_model: str = "multilingual-e5-small",
    ) -> None:
        from src.common.logger import get_logger

        self.logger = get_logger(__name__)

        self.logger.info("[VectorStore.__init__] Initializing VectorStore")
        self.logger.info(f"[VectorStore.__init__] connection_id: {connection_id}")
        self.logger.info(f"[VectorStore.__init__] Engine: {engine}")
        self.logger.info(f"[VectorStore.__init__] Default model: {default_model}")

        self.engine: AsyncEngine = engine
        self.chat_model = chat_model
        self.connection_id = connection_id
        self.default_model = default_model

        # Initialize sentence-transformers model for pgvector
        self.logger.info("[VectorStore.__init__] Loading sentence-transformers model...")
        self.embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        self.logger.info("[VectorStore.__init__] Sentence-transformers model loaded successfully")

        self.logger.info("[VectorStore.__init__] VectorStore initialization completed")

    def set_connection_id(self, connection_id: str) -> None:
        """Switch the active connection scope for subsequent searches."""
        self.connection_id = connection_id

    async def _conn(self) -> AsyncConnection:
        self.logger.info("[VectorStore._conn] Creating database connection")
        try:
            conn = await self.engine.connect()
            self.logger.info(
                f"[VectorStore._conn] Connection created successfully: {conn}"
            )
            return conn
        except Exception as e:
            self.logger.error(f"[VectorStore._conn] Failed to create connection: {e}")
            self.logger.exception("[VectorStore._conn] Full traceback:")
            raise ConnectionException(
                f"Failed to establish database connection: {str(e)}"
            ) from e


    async def search(
        self,
        query_text: str,
        *,
        model: str | None = None,
        limit: int = 10,
        metric: Distance = "COSINE",
        model_options: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        import time

        start_time = time.time()

        self.logger.info(
            "[VectorStore.search] ========== STARTING VECTOR SEARCH =========="
        )
        self.logger.info(
            f"[VectorStore.search] Query text: '{query_text[:100]}...'{' (truncated)' if len(query_text) > 100 else ''}"
        )
        self.logger.info(f"[VectorStore.search] Model: {model}")
        self.logger.info(f"[VectorStore.search] Limit: {limit}")
        self.logger.info(f"[VectorStore.search] Metric: {metric}")
        self.logger.info(f"[VectorStore.search] Model options: {model_options}")
        self.logger.info(f"[VectorStore.search] Additional params: {params}")
        self.logger.info(f"[VectorStore.search] connection_id: {self.connection_id}")
        self.logger.info(f"[VectorStore.search] Engine: {self.engine}")

        if model is None:
            model = self.default_model
            self.logger.info(f"[VectorStore.search] Using default model: {model}")

        options = {"model_id": model}
        if model_options:
            options.update(model_options)

        self.logger.info(f"[VectorStore.search] Final options: {options}")

        self.logger.info(
            f"[VectorStore.search] Generating query embedding at {time.time() - start_time:.3f}s"
        )

        # Generate embedding using sentence-transformers
        query_embedding = self.embedding_model.encode(query_text).tolist()
        self.logger.info(f"[VectorStore.search] Generated embedding with {len(query_embedding)} dimensions")

        self.logger.info(
            f"[VectorStore.search] Building SQL query at {time.time() - start_time:.3f}s"
        )

        # Use pgvector similarity search with cosine distance, scoped to a
        # single connection_id (the metadata DB hosts every connection's
        # embeddings in one shared `notes` table).
        sql = """
            SELECT
                table_name AS id,
                table_name AS text,
                description AS comment,
                full_text AS full_desc,
                columns_info AS desc_cols,
                embedding <=> CAST(:q_embedding AS vector) AS distance
            FROM notes
            WHERE connection_id = CAST(:connection_id AS UUID)
            ORDER BY distance
            LIMIT :lim
        """

        self.logger.info("[VectorStore.search] Generated SQL query:")
        self.logger.info(f"[VectorStore.search] {sql}")
        self.logger.info(
            "[VectorStore.search] Query uses pgvector cosine similarity (<=>)"
        )

        self.logger.info(
            f"[VectorStore.search] Preparing bind parameters at {time.time() - start_time:.3f}s"
        )

        bind = {
            "q_embedding": query_embedding,
            "lim": int(limit),
            "connection_id": self.connection_id,
        }
        if params:
            bind.update(params)

        self.logger.info("[VectorStore.search] Bind parameters:")
        self.logger.info(
            f"[VectorStore.search] - q_embedding: vector with {len(query_embedding)} dimensions"
        )
        self.logger.info(f"[VectorStore.search] - lim: {int(limit)}")
        if params:
            self.logger.info(f"[VectorStore.search] - additional params: {params}")

        self.logger.info(
            f"[VectorStore.search] Starting database connection at {time.time() - start_time:.3f}s"
        )

        try:
            async with self.engine.connect() as conn:
                self.logger.info(
                    f"[VectorStore.search] Database connection established at {time.time() - start_time:.3f}s"
                )
                self.logger.info(f"[VectorStore.search] Connection object: {conn}")

                # Register pgvector type with the raw asyncpg connection
                raw_conn = await conn.get_raw_connection()
                await register_vector(raw_conn.driver_connection)
                self.logger.info("[VectorStore.search] Registered pgvector type with asyncpg connection")

                self.logger.info(
                    f"[VectorStore.search] About to execute pgvector similarity search at {time.time() - start_time:.3f}s"
                )
                self.logger.info(
                    "[VectorStore.search] *** THIS IS THE CRITICAL POINT - PGVECTOR SEARCH EXECUTION ***"
                )

                query_start = time.time()
                try:
                    result = await conn.execute(sqltext(sql), bind)
                except Exception as e:
                    error_msg = str(e).lower()
                    if "ml_embed" in error_msg or "embedding" in error_msg:
                        raise EmbeddingException(
                            f"Failed to generate embeddings with ML_EMBED_ROW: {str(e)}"
                        ) from e
                    else:
                        raise VectorSearchException(
                            f"Vector search query failed: {str(e)}"
                        ) from e
                query_duration = time.time() - query_start

                self.logger.info(
                    f"[VectorStore.search] *** PGVECTOR SEARCH COMPLETED in {query_duration:.3f}s ***"
                )
                self.logger.info(f"[VectorStore.search] Query result object: {result}")

                self.logger.info(
                    f"[VectorStore.search] Fetching all rows at {time.time() - start_time:.3f}s"
                )
                fetch_start = time.time()
                rows = result.fetchall()
                fetch_duration = time.time() - fetch_start

                self.logger.info(
                    f"[VectorStore.search] Fetched {len(rows)} rows in {fetch_duration:.3f}s"
                )
        except (ConnectionException, EmbeddingException, VectorSearchException):
            raise
        except Exception as e:
            self.logger.error(
                f"[VectorStore.search] Unexpected error during search: {e}"
            )
            raise VectorSearchException(
                f"Unexpected error during vector search: {str(e)}"
            ) from e

        self.logger.info(
            f"[VectorStore.search] Processing query results at {time.time() - start_time:.3f}s"
        )

        response = {}
        for i, r in enumerate(rows):
            self.logger.info(
                f"[VectorStore.search] Row {i + 1}: id={r.id}, text='{r.text}', distance={r.distance:.4f}"
            )
            response[r.text] = {
                "id": r.id,
                "table": r.text,
                "distance": float(r.distance),
                "comment": r.comment,
                "full_desc": r.full_desc,
                "desc_cols": r.desc_cols,
            }

        self.logger.info(
            f"[VectorStore.search] Created response dict with {len(response)} tables"
        )
        self.logger.info(f"[VectorStore.search] Table names: {list(response.keys())}")

        self.logger.info(
            f"[VectorStore.search] Starting table filtering at {time.time() - start_time:.3f}s"
        )

        try:
            filter_start = time.time()
            filtered_tables = await self._filter_response(response, query_text)
            filter_duration = time.time() - filter_start

            self.logger.info(
                f"[VectorStore.search] Table filtering completed in {filter_duration:.3f}s"
            )
            self.logger.info(f"[VectorStore.search] Filtered tables: {filtered_tables}")

        except TableFilterException:
            raise
        except Exception as e:
            self.logger.error(f"[VectorStore.search] Table filtering failed: {e}")
            self.logger.exception("[VectorStore.search] Filter error traceback:")
            raise TableFilterException(
                f"Failed to filter relevant tables: {str(e)}"
            ) from e

        self.logger.info(
            f"[VectorStore.search] Building final result at {time.time() - start_time:.3f}s"
        )
        needed_tables = [response[t] for t in filtered_tables if t in response]

        self.logger.info(
            f"[VectorStore.search] Final result: {len(needed_tables)} needed tables"
        )
        for i, table in enumerate(needed_tables):
            self.logger.info(
                f"[VectorStore.search] Result {i + 1}: {table['table']} (distance: {table['distance']:.4f})"
            )

        total_time = time.time() - start_time
        self.logger.info(
            f"[VectorStore.search] ========== VECTOR SEARCH COMPLETED in {total_time:.3f}s =========="
        )

        return needed_tables

    async def _filter_response(
        self,
        response: dict[str, dict[int, str, float, str, str, str]],
        query_text: str,
        max_retry: int = 3,
        temperature: float = 0.8,
        max_tokens: int = 8192,
    ) -> list[str]:
        import time

        start_time = time.time()

        self.logger.info(
            "[VectorStore._filter_response] ========== STARTING TABLE FILTERING =========="
        )
        self.logger.info(
            f"[VectorStore._filter_response] Query text: '{query_text[:100]}...'{' (truncated)' if len(query_text) > 100 else ''}"
        )
        self.logger.info(
            f"[VectorStore._filter_response] Number of tables to filter: {len(response)}"
        )
        self.logger.info(f"[VectorStore._filter_response] Max retry: {max_retry}")
        self.logger.info(f"[VectorStore._filter_response] Temperature: {temperature}")
        self.logger.info(f"[VectorStore._filter_response] Max tokens: {max_tokens}")

        if not response:
            self.logger.warning(
                "[VectorStore._filter_response] No tables found in response to filter"
            )
            print("Warning: No tables found in response to filter")
            return []

        self.logger.info(
            f"[VectorStore._filter_response] Building description for filtering at {time.time() - start_time:.3f}s"
        )

        desc_for_filtering = "Tabels:\n"

        for i, (tbl, rec) in enumerate(response.items(), start=1):
            comment = rec['comment'] or "No description available"
            table_line = f"{i}. {rec['table']}: {comment}\n"
            desc_for_filtering += table_line
            self.logger.info(
                f"[VectorStore._filter_response] Table {i}: {rec['table']} - {comment[:100]}..."
            )

        desc_for_filtering += "User question:\n" + query_text

        self.logger.info(
            f"[VectorStore._filter_response] Filter description length: {len(desc_for_filtering)}"
        )
        self.logger.info(
            f"[VectorStore._filter_response] Filter description preview: {desc_for_filtering[:300]}..."
        )

        try:
            self.logger.info(
                f"[VectorStore._filter_response] Preparing chat messages at {time.time() - start_time:.3f}s"
            )

            messages = [
                SystemMessage(content=SYSTEM_FILTER_PROMPT),
                HumanMessage(content=desc_for_filtering),
            ]

            self.logger.info(
                f"[VectorStore._filter_response] Created {len(messages)} messages for chat model"
            )
            self.logger.info(
                f"[VectorStore._filter_response] System prompt length: {len(SYSTEM_FILTER_PROMPT)}"
            )
            self.logger.info(
                f"[VectorStore._filter_response] Human message length: {len(desc_for_filtering)}"
            )

            self.logger.info(
                f"[VectorStore._filter_response] Invoking chat model at {time.time() - start_time:.3f}s"
            )
            self.logger.info(
                f"[VectorStore._filter_response] Chat model: {self.chat_model}"
            )

            chat_start = time.time()
            try:
                # Don't pass max_tokens here — the chat_model was already
                # built with its own per-model max_tokens budget (see
                # llm/utils.create_llm_from_settings). Forwarding 8192
                # crashes models with smaller completion caps like
                # gpt-3.5-turbo (4096 max).
                chat_resp = await self.chat_model.ainvoke(
                    messages,
                    temperature=temperature,
                )
            except Exception as e:
                self.logger.error(
                    f"[VectorStore._filter_response] Chat model invocation failed: {e}"
                )
                raise TableFilterException(
                    f"Failed to invoke LLM for table filtering: {str(e)}"
                ) from e
            chat_duration = time.time() - chat_start

            self.logger.info(
                f"[VectorStore._filter_response] Chat model completed in {chat_duration:.3f}s"
            )
            self.logger.info(
                f"[VectorStore._filter_response] Response type: {type(chat_resp)}"
            )
            self.logger.info(
                f"[VectorStore._filter_response] Response content length: {len(chat_resp.content)}"
            )
            self.logger.info(
                f"[VectorStore._filter_response] Response content preview: {chat_resp.content[:200]}..."
            )

            self.logger.info(
                f"[VectorStore._filter_response] Parsing response at {time.time() - start_time:.3f}s"
            )
            answer = []

            for retry_attempt in range(max_retry):
                try:
                    self.logger.info(
                        f"[VectorStore._filter_response] Parse attempt {retry_attempt + 1}/{max_retry}"
                    )
                    parsed_response = json.loads(chat_resp.content)
                    self.logger.info(
                        f"[VectorStore._filter_response] Successfully parsed JSON: {parsed_response}"
                    )
                    answer = parsed_response["needed_tables"]
                    self.logger.info(
                        f"[VectorStore._filter_response] Extracted needed_tables: {answer}"
                    )
                    break
                except JSONDecodeError as e:
                    self.logger.warning(
                        f"[VectorStore._filter_response] JSON parse attempt {retry_attempt + 1} failed: {e}"
                    )
                    self.logger.warning(
                        f"[VectorStore._filter_response] Raw content: {chat_resp.content[:500]}..."
                    )
                    continue
                except KeyError as e:
                    self.logger.error(
                        f"[VectorStore._filter_response] Key error on attempt {retry_attempt + 1}: {e}"
                    )
                    self.logger.error(
                        f"[VectorStore._filter_response] Parsed JSON keys: {list(parsed_response.keys())}"
                    )
                    continue

            if not answer:
                self.logger.warning(
                    "[VectorStore._filter_response] Could not parse needed_tables from LLM response, returning all tables"
                )
                self.logger.warning(
                    f"[VectorStore._filter_response] Final raw response: {chat_resp.content}"
                )
                print(
                    "Warning: Could not parse needed_tables from LLM response, returning all tables"
                )
                fallback_result = list(response.keys())
                self.logger.info(
                    f"[VectorStore._filter_response] Returning fallback result: {fallback_result}"
                )
                return fallback_result

            self.logger.info(
                f"[VectorStore._filter_response] Successfully filtered to {len(answer)} tables"
            )
            self.logger.info(
                f"[VectorStore._filter_response] Filtered result: {answer}"
            )
            return answer

        except TableFilterException:
            raise
        except Exception as e:
            error_time = time.time() - start_time
            self.logger.error(
                f"[VectorStore._filter_response] *** FILTERING FAILED at {error_time:.3f}s ***"
            )
            self.logger.error(f"[VectorStore._filter_response] Error type: {type(e)}")
            self.logger.error(f"[VectorStore._filter_response] Error message: {e}")
            self.logger.exception("[VectorStore._filter_response] Full traceback:")
            print(f"Error in table filtering: {str(e)}")

            # Still return fallback but wrap in exception for proper handling
            fallback_result = list(response.keys())
            self.logger.warning(
                f"[VectorStore._filter_response] Using fallback result after error: {fallback_result}"
            )
            # Return fallback without raising to maintain backward compatibility
            return fallback_result
        finally:
            total_time = time.time() - start_time
            self.logger.info(
                f"[VectorStore._filter_response] ========== TABLE FILTERING COMPLETED in {total_time:.3f}s =========="
            )

    async def close(self) -> None:
        """Close the database engine."""
        self.logger.info("[VectorStore.close] Closing database engine")
        try:
            await self.engine.dispose()
            self.logger.info("[VectorStore.close] Database engine closed successfully")
        except Exception as e:
            self.logger.error(
                f"[VectorStore.close] Failed to close database engine: {e}"
            )
            self.logger.exception("[VectorStore.close] Close error traceback:")
            raise ConnectionException(
                f"Failed to close database connection: {str(e)}"
            ) from e
