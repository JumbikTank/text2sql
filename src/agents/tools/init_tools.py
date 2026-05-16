import json
from contextvars import ContextVar
from typing import Any

import sqlparse
from langchain_core.tools import tool
from langchain_core.language_models import BaseChatModel

from src.agents.tools.df_to_text_converter import DataFrameToTextConverter
from src.agents.tools.sql_executor import SQLExecutor
from src.agents.tools.required_tables_searcher import VectorStore
from src.agents.tools.sql_creator import SQLCreator
from src.agents.tools.controller import SQLController
from src.agents.tools.schema_aligner import SchemaAligner, Alignment
from src.agents.tools.sql_validator import (
    is_sql_valid,
    build_correction_prompt,
)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from src.agents.tools.prompt_templates import SYSTEM_FOLLOW_UP_PROMPT

from uuid import uuid4
import os
from src.common.settings import get_settings
from pathlib import Path

_chat_model: BaseChatModel | None = None
_vector_store: VectorStore | None = None
_sql_creator: SQLCreator | None = None
_sql_controller: SQLController | None = None
_executor: SQLExecutor | None = None
_df_to_text: DataFrameToTextConverter | None = None
_schema_aligner: SchemaAligner | None = None

# Side-channel for evidence/hints that don't belong in the user-facing
# question text but should be surfaced to the SQL creator as a separate
# labelled section. Set by bench harnesses or callers that have access
# to structured hints; the agent's message-driven flow leaves it unset.
_evidence_var: ContextVar[str] = ContextVar("evidence", default="")


def set_evidence(evidence: str) -> None:
    _evidence_var.set(evidence or "")


def get_evidence() -> str:
    return _evidence_var.get()


_BARE_FALLBACK_SYSTEM = (
    "You are an expert PostgreSQL query writer. Given a schema and a "
    "question, write exactly one PostgreSQL SELECT statement that "
    "answers the question. Use only the tables and columns shown. "
    "Return ONLY the columns explicitly asked for. Singular phrasing "
    "implies LIMIT 1. For percentages, use NULLIF on the denominator "
    "and CAST the numerator to REAL. Output strict JSON: "
    '{"sql_query": "<your SELECT>"}. Return nothing else.'
)


async def _bare_fallback_sql(
    question: str, relevant_tables: list[dict], evidence: str = ""
) -> str | None:
    """Single-shot fallback. Skips sql_creator, controller, validator,
    correction loop. Useful when the retry loop has exhausted on a
    pattern the model keeps re-producing; a fresh prompt with no prior
    context often breaks the loop."""
    if _chat_model is None or not relevant_tables:
        return None

    # Render schema in BIRD-style canonical form using what's already
    # in the embedding rows (no value hints; column types + FKs).
    parts: list[str] = []
    for t in relevant_tables:
        name = t.get("table") or t.get("text") or "?"
        full = (t.get("full_desc") or t.get("desc_cols") or "").split("|", 1)[0].strip()
        if full:
            parts.append(f"Table {name}:\n  {full}")
    schema = "\n\n".join(parts)

    evidence_block = f"\n\nEvidence: {evidence}" if evidence else ""
    user_msg = (
        f"Schema:\n{schema}\n\n"
        f"Question: {question}{evidence_block}\n\n"
        'Return only {"sql_query": "..."}.'
    )

    try:
        resp = await _chat_model.ainvoke(
            [SystemMessage(content=_BARE_FALLBACK_SYSTEM),
             HumanMessage(content=user_msg)],
            temperature=0.0,
        )
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception:
        return None

    # Extract SQL from the response. Try JSON, then code-fence, then raw.
    import re as _re
    try:
        m = _re.search(r"\{.*\"sql_query\".*\}", content, _re.DOTALL)
        if m:
            obj = json.loads(m.group(0))
            sql = obj.get("sql_query")
            if isinstance(sql, str) and sql.strip():
                return sql.strip()
    except (json.JSONDecodeError, ValueError):
        pass
    m = _re.search(r"```(?:sql)?\s*([\s\S]+?)```", content, _re.IGNORECASE)
    if m:
        return m.group(1).strip()
    if _re.match(r"^\s*(SELECT|WITH)\b", content, _re.IGNORECASE):
        return content.strip()
    return None

# Per-request cache of the last retrieved tables, used by follow_up.
# ContextVar ensures concurrent async requests don't overwrite each other.
_last_tables_var: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "last_tables", default=None
)


def set_last_tables(tables: list[dict[str, Any]]) -> None:
    _last_tables_var.set(tables)


def get_last_tables() -> list[dict[str, Any]] | None:
    return _last_tables_var.get()

settings = get_settings()


# Custom exceptions for better error handling
class ToolException(Exception):
    """Base exception for tool errors"""

    pass


class VectorSearchException(ToolException):
    """Exception raised when vector search fails"""

    pass


class SQLGenerationException(ToolException):
    """Exception raised when SQL generation fails"""

    pass


class SQLExecutionException(ToolException):
    """Exception raised when SQL execution fails"""

    pass


class NoRelevantTablesException(ToolException):
    """Exception raised when no relevant tables are found"""

    pass


class InvalidSQLException(ToolException):
    """Exception raised when generated SQL is invalid"""

    pass


class DataConversionException(ToolException):
    """Exception raised when data conversion fails"""

    pass


class MissingContextException(ToolException):
    """Exception raised when required context is missing"""

    pass


def initialize_components(
    chat_model: BaseChatModel,
    vector_store: VectorStore,
    sql_creator: SQLCreator,
    sql_controller: SQLController,
    executor: SQLExecutor,
    df_to_text: DataFrameToTextConverter,
) -> None:
    """Initialize all components for the facade functions."""
    from src.common.logger import get_logger

    logger = get_logger(__name__)

    logger.info("[initialize_components] Starting component initialization")

    global \
        _chat_model, \
        _vector_store, \
        _sql_creator, \
        _sql_controller, \
        _executor, \
        _df_to_text, \
        _schema_aligner, \
        _text_to_sql

    _chat_model = chat_model
    _schema_aligner = SchemaAligner(chat_model)
    logger.info(f"[initialize_components] Chat model initialized: {chat_model}")

    _vector_store = vector_store
    logger.info(f"[initialize_components] Vector store initialized: {vector_store}")
    logger.info(
        f"[initialize_components] Vector store connection_id: {vector_store.connection_id}"
    )
    logger.info(f"[initialize_components] Vector store engine: {vector_store.engine}")

    _sql_creator = sql_creator
    logger.info(f"[initialize_components] SQL creator initialized: {sql_creator}")

    _sql_controller = sql_controller
    logger.info(f"[initialize_components] SQL controller initialized: {sql_controller}")

    _executor = executor
    logger.info(f"[initialize_components] SQL executor initialized: {executor}")

    _df_to_text = df_to_text
    logger.info(
        f"[initialize_components] DataFrame converter initialized: {df_to_text}"
    )

    logger.info("[initialize_components] All components initialized successfully")


def find_project_root(markers=("pyproject.toml", ".git", "setup.cfg")) -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if any((parent / m).exists() for m in markers):
            return parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = find_project_root()
DEFAULT_CSV_DIR = PROJECT_ROOT / "tmp" / "csv"


def get_csv_dir() -> Path:
    """Get CSV directory path without creating it."""
    raw = getattr(settings, "csv_export_path", None)
    if not raw:
        return DEFAULT_CSV_DIR
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def ensure_csv_dir() -> Path:
    """Ensure CSV directory exists, creating it if necessary."""
    csv_dir = get_csv_dir()
    try:
        csv_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        import tempfile

        fallback_dir = Path(tempfile.gettempdir()) / "text2sql_csv"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir
    return csv_dir


@tool("generate_sql_query", description="Generate a query based on a user question")
async def generate_sql_query(
    question: str,
    model: str = "multilingual-e5-small",
    temperature: float = 0,
    max_tokens: int = 10000,
) -> dict[str, str]:
    from src.common.logger import get_logger
    import time

    logger = get_logger(__name__)

    start_time = time.time()
    logger.info(f"[generate_sql_query] Starting with question: {question[:100]}...")
    logger.info(
        f"[generate_sql_query] Parameters: model={model}, temperature={temperature}, max_tokens={max_tokens}"
    )

    logger.info(
        f"[generate_sql_query] Starting vector search at {time.time() - start_time:.2f}s"
    )
    logger.info(f"[generate_sql_query] Vector store object: {_vector_store}")
    logger.info(
        f"[generate_sql_query] Calling _vector_store.search with question='{question[:50]}...', model={model}, limit=5"
    )

    try:
        search_start = time.time()
        relevant_tables = await _vector_store.search(
            query_text=question, model=model, limit=14
        )
        search_duration = time.time() - search_start
        logger.info(
            f"[generate_sql_query] Vector search completed in {search_duration:.2f}s"
        )
        logger.info(
            f"[generate_sql_query] Found {len(relevant_tables)} relevant tables"
        )
        for i, table in enumerate(relevant_tables):
            logger.info(f"[generate_sql_query] Table {i + 1}: {table}")

        if not relevant_tables:
            raise NoRelevantTablesException(
                "No relevant tables found for your question. Please try rephrasing or be more specific."
            )
    except NoRelevantTablesException:
        raise
    except Exception as e:
        logger.error(f"[generate_sql_query] Vector search failed: {e}")
        logger.exception("[generate_sql_query] Full traceback:")
        raise VectorSearchException(
            "Failed to search for relevant database tables. Please try again later."
        ) from e

    # Schema alignment (TA-SQL style) was tried and measured to hurt
    # accuracy by ~2pp on BIRD Mini-Dev — see
    # memory/pipeline_vs_bare_findings.md. Disabled. The module remains
    # on disk (schema_aligner.py) for future experiments.
    question_for_sql = question
    evidence = get_evidence()

    # Q-SQL retrieval (BENCH_QSQL=1): retrieve top-K analogous queries
    # from BIRD train.parquet. Cross-DB (train/dev are disjoint by
    # design); model copies SQL patterns and BIRD-style idioms.
    # BENCH_QSQL_MIN_SCORE filters out low-similarity examples that
    # tend to mislead more than help.
    qsql_examples: list[dict] = []
    if os.getenv("BENCH_QSQL") == "1":
        try:
            from src.agents.tools.qsql_retriever import build_retriever
            qsql_k = int(os.getenv("BENCH_QSQL_K", "3"))
            qsql_min = float(os.getenv("BENCH_QSQL_MIN_SCORE", "0.40"))
            retriever = build_retriever()
            qsql_start = time.time()
            results = retriever.retrieve(
                question_for_sql, k=qsql_k, min_score=qsql_min
            )
            qsql_examples = [
                {
                    "question": r.question,
                    "sql": r.sql,
                    "evidence": r.evidence,
                    "db_id": r.db_id,
                    "score": r.score,
                }
                for r in results
            ]
            logger.info(
                f"[generate_sql_query] Q-SQL retrieval returned "
                f"{len(qsql_examples)} examples (min_score={qsql_min}) in "
                f"{time.time() - qsql_start:.2f}s"
            )
        except Exception as qe:
            logger.warning(f"[generate_sql_query] Q-SQL retrieval failed: {qe}")
            qsql_examples = []

    logger.info(
        f"[generate_sql_query] Starting SQL creation at {time.time() - start_time:.2f}s"
    )
    logger.info("[generate_sql_query] Calling _sql_creator.create_sql")

    try:
        sql_start = time.time()
        sql_response, desc = await _sql_creator.create_sql(
            question=question_for_sql,
            list_tables=relevant_tables,
            evidence=evidence,
            examples=qsql_examples,
            temperature=temperature,
            max_tokens=max_tokens,
            validate_columns_flag=False,  # Rely on execution error loop
        )
        sql_duration = time.time() - sql_start
        logger.info(
            f"[generate_sql_query] SQL creation completed in {sql_duration:.2f}s"
        )
        logger.info(f"[generate_sql_query] SQL response type: {type(sql_response)}")
        logger.info(
            f"[generate_sql_query] SQL response preview: {str(sql_response)[:200]}..."
        )
    except Exception as e:
        logger.error(f"[generate_sql_query] SQL creation failed: {e}")
        logger.exception("[generate_sql_query] Full traceback:")
        raise SQLGenerationException(
            "Failed to generate SQL query from your question. Please try rephrasing your question."
        ) from e

    try:
        sql_data = json.loads(sql_response)
        sql_query = sql_data["sql_query"]
        logger.info("[generate_sql_query] Successfully parsed JSON response")
    except (json.JSONDecodeError, KeyError) as e:
        # Try to use raw response as fallback
        sql_query = sql_response
        logger.info(
            f"[generate_sql_query] Using raw response as SQL query (parse error: {e})"
        )

        # Validate that we have something that looks like SQL
        if not sql_query or not any(
            keyword in sql_query.upper() for keyword in ["SELECT", "WITH"]
        ):
            raise InvalidSQLException(
                "The generated response does not appear to be a valid SQL query."
            )

    # Step: SQL syntax validation with sqlglot
    logger.info(
        f"[generate_sql_query] Starting SQL syntax validation at {time.time() - start_time:.2f}s"
    )
    validation_result = is_sql_valid(sql_query, dialect="postgres")

    if not validation_result.if_valid:
        logger.warning(
            f"[generate_sql_query] SQL syntax validation failed: {validation_result.error_message}"
        )
        # Will attempt self-correction during execution phase
    else:
        logger.info("[generate_sql_query] SQL syntax validation passed")

    set_last_tables(relevant_tables)
    logger.info(
        f"[generate_sql_query] Cached {len(relevant_tables)} tables for follow-up"
    )

    # Step: SQL Controller validation/correction
    logger.info(
        f"[generate_sql_query] Starting SQL validation at {time.time() - start_time:.2f}s"
    )

    if _sql_controller:
        try:
    
            logger.info(
                f"[generate_sql_query] Calling SQL controller with query length: {len(sql_query)}"
            )

            controller_start = time.time()

            validated_sql = await _sql_controller.control(
                sql_query=sql_query,
                user_question=question,
                table_info=desc,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            controller_duration = time.time() - controller_start

            logger.info(
                f"[generate_sql_query] SQL controller completed in {controller_duration:.2f}s"
            )

            # Check if controller returned empty string (invalid SQL)
            if not validated_sql or not validated_sql.strip():
                logger.warning(
                    "[generate_sql_query] Controller returned empty SQL - query cannot be answered with SELECT"
                )
                raise InvalidSQLException(
                    "The question cannot be answered with a read-only SQL query."
                )

            sql_query = validated_sql

        except InvalidSQLException:
            raise
        except Exception as e:
            logger.error(f"[generate_sql_query] SQL controller failed: {e}")
            logger.exception("[generate_sql_query] Controller traceback:")
            # Continue with original SQL if controller fails
            logger.warning(
                "[generate_sql_query] Using original SQL after controller failure"
            )
    else:
        logger.warning(
            "[generate_sql_query] SQL controller not initialized, skipping validation"
        )

    logger.info("[generate_sql_query] Formatting SQL query")
    sql_formatted = sqlparse.format(sql_query, reindent=True, keyword_case="upper")
    logger.info(
        f"[generate_sql_query] SQL query formatted, length: {len(sql_formatted)}"
    )

    # Step 4: Execute SQL with self-correction loop
    logger.info(
        f"[generate_sql_query] Step 4: Starting SQL execution at {time.time() - start_time:.2f}s"
    )
    logger.info(f"[generate_sql_query] Executor object: {_executor}")

    max_retries = 3
    current_sql = sql_query
    last_error = None
    df = None
    correction_history: list[tuple[str, str]] = []

    for attempt in range(max_retries):
        try:
            exec_start = time.time()
            df = await _executor.query(current_sql)
            exec_duration = time.time() - exec_start
            logger.info(
                f"[generate_sql_query] SQL execution completed in {exec_duration:.2f}s "
                f"(attempt {attempt + 1})"
            )
            logger.info(f"[generate_sql_query] Result DataFrame shape: {df.shape}")
            logger.info(f"[generate_sql_query] Result DataFrame columns: {list(df.columns)}")

            if df.empty:
                logger.warning("[generate_sql_query] Query returned no results")

            # Success - update formatted SQL and break
            sql_formatted = sqlparse.format(current_sql, reindent=True, keyword_case="upper")
            break

        except Exception as e:
            last_error = e
            error_str = str(e)
            logger.warning(
                f"[generate_sql_query] SQL execution failed (attempt {attempt + 1}/{max_retries}): {error_str}"
            )

            # Check for non-retryable errors
            error_lower = error_str.lower()
            if "permission" in error_lower or "denied" in error_lower:
                raise SQLExecutionException(
                    "Database access denied. Please contact your administrator."
                ) from e
            if "timeout" in error_lower or "timed out" in error_lower:
                raise SQLExecutionException(
                    "The query took too long to execute. Please try a simpler question."
                ) from e

            # Record this failure so the next correction attempt sees the
            # full chain (and can avoid producing the same broken pattern).
            correction_history.append((current_sql, error_str))

            # If we have more retries, attempt self-correction
            if attempt < max_retries - 1:
                logger.info(
                    f"[generate_sql_query] Attempting self-correction (attempt {attempt + 2})"
                )
                try:
                    # Build correction prompt with full prior history.
                    # Passing relevant_tables lets the diagnoser look up
                    # the *real* owning table for a missing column and
                    # tell the model exactly where to find it.
                    correction_prompt = build_correction_prompt(
                        original_question=question,
                        failed_sql=current_sql,
                        error_message=error_str,
                        attempt=attempt + 1,
                        history=correction_history[:-1],
                        relevant_tables=relevant_tables,
                        original_evidence=evidence,
                    )

                    # Call LLM for correction
                    correction_response, _ = await _sql_creator.create_sql(
                        question=correction_prompt,
                        list_tables=relevant_tables,
                        evidence=evidence,
                        temperature=0.0,  # Use low temperature for corrections
                        max_tokens=max_tokens,
                        correction_mode=True,
                        validate_columns_flag=False,
                    )

                    # Parse corrected SQL
                    try:
                        correction_data = json.loads(correction_response)
                        corrected_sql = correction_data.get("sql_query", "")
                    except json.JSONDecodeError:
                        corrected_sql = correction_response

                    if corrected_sql and corrected_sql.strip():
                        logger.info(
                            f"[generate_sql_query] Got corrected SQL, length: {len(corrected_sql)}"
                        )
                        current_sql = corrected_sql
                    else:
                        logger.warning(
                            "[generate_sql_query] Self-correction returned empty SQL"
                        )

                except Exception as correction_error:
                    logger.error(
                        f"[generate_sql_query] Self-correction failed: {correction_error}"
                    )
                    # Continue to next retry with same SQL

    # If all retries exhausted: try a single-shot bare fallback before
    # giving up. The retry loop sometimes converges on a wrong pattern
    # the model keeps reinforcing; one fresh attempt with just schema +
    # question (no prior-attempts context, no correction prompt) often
    # gets it right when retries cannot.
    if df is None:
        logger.warning(
            f"[generate_sql_query] All {max_retries} attempts failed — "
            f"trying single-shot bare fallback"
        )
        try:
            fallback_sql = await _bare_fallback_sql(
                question, relevant_tables, evidence=evidence
            )
            if fallback_sql:
                df = await _executor.query(fallback_sql)
                current_sql = fallback_sql
                sql_formatted = sqlparse.format(
                    fallback_sql, reindent=True, keyword_case="upper"
                )
                logger.info(
                    "[generate_sql_query] Bare fallback succeeded after "
                    "retry-loop exhaustion"
                )
        except Exception as fb_err:
            logger.warning(
                f"[generate_sql_query] Bare fallback also failed: {fb_err}"
            )

    if df is None:
        logger.error(f"[generate_sql_query] All {max_retries} attempts failed")
        raise SQLExecutionException(
            "Failed to execute the database query after multiple attempts. "
            "Please try rephrasing your question."
        ) from last_error

    # Step 5: Convert DataFrame to natural language answer
    logger.info(
        f"[generate_sql_query] Step 5: Converting to natural language at {time.time() - start_time:.2f}s"
    )

    try:
        convert_start = time.time()
        natural_language_answer = await _df_to_text.answer(
            df=df,
            user_question=question,
            list_tables=relevant_tables,
            sql=sql_formatted,
            temperature=temperature,
        )
        convert_duration = time.time() - convert_start
        logger.info(f"[generate_sql_query] Text conversion completed in {convert_duration:.2f}s")
        logger.info(f"[generate_sql_query] Answer length: {len(natural_language_answer)}")
    except Exception as e:
        logger.error(f"[generate_sql_query] Text conversion failed: {e}")
        logger.exception("[generate_sql_query] Full traceback:")
        raise DataConversionException(
            "Failed to generate a natural language response. Please try again."
        ) from e

    response = {
        "type": "text",
        "content": natural_language_answer,
        "sql": sql_formatted,
        "error": "",
    }

    total_time = time.time() - start_time
    logger.info(f"[generate_sql_query] Completed successfully in {total_time:.2f}s")
    logger.info(
        f"[generate_sql_query] Returning response with answer of length {len(natural_language_answer)}"
    )
    return response


@tool("show_table", description="Output a table with the result the user requested")
async def show_table(
    question: str,
    model: str = "multilingual-e5-small",
    temperature: float = 0,
    max_tokens: int = 10000,
) -> dict[str, str]:
    """
    Generates a sql query and executes it based on the user's query. For example, "Show me how many people listen to this artist by year"

    Key words: "show", "bring out", "create pivot table" and similar ones

    This function:
    1. Uses VectorStore to find relevant database tables
    2. Uses SQLCreator to generate SQL query
    3. Uses SQLExecutor to run the query and return DataFrame as formatted string

    Args:
        question: Natural language question about data

    Returns:
        Formatted table results as string (markdown format)
    """
    from src.common.logger import get_logger
    import time

    logger = get_logger(__name__)

    start_time = time.time()
    logger.info(f"[show_table] Starting with question: {question[:100]}...")
    logger.info(
        f"[show_table] Parameters: model={model}, temperature={temperature}, max_tokens={max_tokens}"
    )

    # Step 1: Find relevant tables using vector search
    logger.info(
        f"[show_table] Step 1: Starting vector search at {time.time() - start_time:.2f}s"
    )
    logger.info(f"[show_table] Vector store object: {_vector_store}")
    logger.info(
        f"[show_table] Calling _vector_store.search with question='{question[:50]}...', model={model}, limit=5"
    )

    try:
        search_start = time.time()
        relevant_tables = await _vector_store.search(
            query_text=question, model=model, limit=14
        )
        search_duration = time.time() - search_start
        logger.info(f"[show_table] Vector search completed in {search_duration:.2f}s")
        logger.info(f"[show_table] Found {len(relevant_tables)} relevant tables")
        for i, table in enumerate(relevant_tables):
            logger.info(
                f"[show_table] Table {i + 1}: {table.get('table') if isinstance(table, dict) else table}"
            )

        if not relevant_tables:
            raise NoRelevantTablesException(
                "No relevant tables found for your question. Please try rephrasing or be more specific."
            )
    except NoRelevantTablesException:
        raise
    except Exception as e:
        logger.error(f"[show_table] Vector search failed: {e}")
        logger.exception("[show_table] Full traceback:")
        raise VectorSearchException(
            "Failed to search for relevant database tables. Please try again later."
        ) from e

    # Step 2: Generate SQL query using SQLCreator
    logger.info(
        f"[show_table] Step 2: Starting SQL creation at {time.time() - start_time:.2f}s"
    )
    logger.info(
        f"[show_table] Calling _sql_creator.create_sql with {len(relevant_tables)} tables"
    )

    evidence = get_evidence()

    try:
        sql_start = time.time()
        sql_response, desc = await _sql_creator.create_sql(
            question=question,
            list_tables=relevant_tables,
            evidence=evidence,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        sql_duration = time.time() - sql_start
        logger.info(f"[show_table] SQL creation completed in {sql_duration:.2f}s")
        logger.info(f"[show_table] SQL response type: {type(sql_response)}")
        logger.info(f"[show_table] SQL response preview: {str(sql_response)[:200]}...")
    except Exception as e:
        logger.error(f"[show_table] SQL creation failed: {e}")
        logger.exception("[show_table] Full traceback:")
        raise SQLGenerationException(
            "Failed to generate SQL query from your question. Please try rephrasing your question."
        ) from e

    # Parse SQL from response
    logger.info(f"[show_table] Parsing SQL response at {time.time() - start_time:.2f}s")
    try:
        sql_data = json.loads(sql_response)
        sql_query = sql_data["sql_query"]
        logger.info("[show_table] Successfully parsed JSON response")
    except (json.JSONDecodeError, KeyError) as e:
        sql_query = sql_response
        logger.info(f"[show_table] Using raw response as SQL query (parse error: {e})")

        # Validate that we have something that looks like SQL
        if not sql_query or not any(
            keyword in sql_query.upper() for keyword in ["SELECT", "WITH"]
        ):
            raise InvalidSQLException(
                "The generated response does not appear to be a valid SQL query."
            )

    logger.info(
        f"[show_table] SQL query: {sql_query[:200]}..."
        if len(sql_query) > 200
        else f"[show_table] SQL query: {sql_query}"
    )

    # Step: SQL Controller validation/correction
    logger.info(
        f"[show_table] Starting SQL validation at {time.time() - start_time:.2f}s"
    )

    if _sql_controller:
        try:
    
            logger.info(
                f"[show_table] Calling SQL controller with query length: {len(sql_query)}"
            )

            controller_start = time.time()

            validated_sql = await _sql_controller.control(
                sql_query=sql_query,
                user_question=question,
                table_info=desc,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            controller_duration = time.time() - controller_start

            logger.info(
                f"[show_table] SQL controller completed in {controller_duration:.2f}s"
            )

            # Check if controller returned empty string (invalid SQL)
            if not validated_sql or not validated_sql.strip():
                logger.warning(
                    "[show_table] Controller returned empty SQL - query cannot be answered with SELECT"
                )
                raise InvalidSQLException(
                    "The question cannot be answered with a read-only SQL query."
                )

            sql_query = validated_sql

        except InvalidSQLException:
            raise
        except Exception as e:
            logger.error(f"[show_table] SQL controller failed: {e}")
            logger.exception("[show_table] Controller traceback:")
            # Continue with original SQL if controller fails
            logger.warning(
                "[show_table] Using original SQL after controller failure"
            )
    else:
        logger.warning(
            "[show_table] SQL controller not initialized, skipping validation"
        )

    # Step 3: Execute SQL with self-correction loop
    logger.info(
        f"[show_table] Step 3: Starting SQL execution at {time.time() - start_time:.2f}s"
    )
    logger.info(f"[show_table] Executor object: {_executor}")

    max_retries = 3
    current_sql = sql_query
    last_error = None
    df = None
    correction_history: list[tuple[str, str]] = []

    for attempt in range(max_retries):
        try:
            exec_start = time.time()
            df = await _executor.query(current_sql)
            exec_duration = time.time() - exec_start
            logger.info(
                f"[show_table] SQL execution completed in {exec_duration:.2f}s "
                f"(attempt {attempt + 1})"
            )
            logger.info(f"[show_table] Result DataFrame shape: {df.shape}")
            logger.info(f"[show_table] Result DataFrame columns: {list(df.columns)}")

            if df.empty:
                logger.warning("[show_table] Query returned no results")

            # Success - update sql_query for formatting later
            sql_query = current_sql
            break

        except Exception as e:
            last_error = e
            error_str = str(e)
            logger.warning(
                f"[show_table] SQL execution failed (attempt {attempt + 1}/{max_retries}): {error_str}"
            )

            # Check for non-retryable errors
            error_lower = error_str.lower()
            if "permission" in error_lower or "denied" in error_lower:
                raise SQLExecutionException(
                    "Database access denied. Please contact your administrator."
                ) from e
            if "timeout" in error_lower or "timed out" in error_lower:
                raise SQLExecutionException(
                    "The query took too long to execute. Please try a simpler question."
                ) from e

            correction_history.append((current_sql, error_str))

            # If we have more retries, attempt self-correction
            if attempt < max_retries - 1:
                logger.info(
                    f"[show_table] Attempting self-correction (attempt {attempt + 2})"
                )
                try:
                    correction_prompt = build_correction_prompt(
                        original_question=question,
                        failed_sql=current_sql,
                        error_message=error_str,
                        attempt=attempt + 1,
                        history=correction_history[:-1],
                        relevant_tables=relevant_tables,
                        original_evidence=evidence,
                    )

                    correction_response, _ = await _sql_creator.create_sql(
                        question=correction_prompt,
                        list_tables=relevant_tables,
                        evidence=evidence,
                        temperature=0.0,
                        max_tokens=max_tokens,
                        validate_columns_flag=False,
                        correction_mode=True,
                    )

                    try:
                        correction_data = json.loads(correction_response)
                        corrected_sql = correction_data.get("sql_query", "")
                    except json.JSONDecodeError:
                        corrected_sql = correction_response

                    if corrected_sql and corrected_sql.strip():
                        logger.info(
                            f"[show_table] Got corrected SQL, length: {len(corrected_sql)}"
                        )
                        current_sql = corrected_sql
                    else:
                        logger.warning("[show_table] Self-correction returned empty SQL")

                except Exception as correction_error:
                    logger.error(f"[show_table] Self-correction failed: {correction_error}")

    if df is None:
        logger.error(f"[show_table] All {max_retries} attempts failed")
        raise SQLExecutionException(
            "Failed to execute the database query after multiple attempts. "
            "Please try rephrasing your question."
        ) from last_error

    # Get settings and ensure CSV export directory exists
    logger.info(f"[show_table] Preparing CSV export at {time.time() - start_time:.2f}s")
    csv_dir = ensure_csv_dir()
    logger.info(f"[show_table] CSV directory: {csv_dir}")

    fn = f"{uuid4()}.csv"
    csv_path = os.path.join(csv_dir, fn)
    logger.info(f"[show_table] Writing CSV to: {csv_path}")
    df.to_csv(csv_path, index=False)
    logger.info("[show_table] CSV file written successfully")

    set_last_tables(relevant_tables)
    logger.info(f"[show_table] Cached {len(relevant_tables)} tables for follow-up")

    # Generate preview data (first 10 rows in horizontal table format)
    preview_df = df.head(10)

    # Convert to horizontal markdown table (traditional format)
    preview_markdown = preview_df.to_markdown(index=False)
    logger.info(f"[show_table] Generated horizontal preview with {len(preview_df)} rows")

    # Format SQL query for better readability
    formatted_sql = sqlparse.format(
        sql_query,
        reindent=True,
        keyword_case='upper',
        indent_width=2
    )

    payload = {
        "type": "text_with_csv",
        "download_link": {"csv": f"{settings.csv_download_base_url}/{fn}"},
        "sql_query": formatted_sql,
        "preview_data": preview_markdown,
        "error": "",
    }

    total_time = time.time() - start_time
    logger.info(f"[show_table] Completed successfully in {total_time:.2f}s")
    logger.info(f"[show_table] Returning payload with CSV filename: {fn}")
    return payload


@tool("follow_up", description="Answer to the user's additional question")
async def follow_up(
    modification: str, prev_sql: str, temperature: float = 0, max_tokens: int = 10000
) -> dict[str, str]:
    """
    An answer to an additional user question based on the previous answer, when the sql query has already
    been generated and an answer given. For example, "And for such a performer?"

    Args:
        modification: User's request for how to modify the previous query

    Returns:
        New modified SQL query as string, or error message if no previous context
    """
    from src.common.logger import get_logger
    import time

    logger = get_logger(__name__)

    start_time = time.time()
    logger.info(f"[follow_up] Starting with modification: {modification[:100]}...")
    logger.info(
        f"[follow_up] Previous SQL preview: {prev_sql[:100]}..."
        if prev_sql
        else "[follow_up] No previous SQL"
    )
    logger.info(
        f"[follow_up] Parameters: temperature={temperature}, max_tokens={max_tokens}"
    )

    last_tables = get_last_tables()
    logger.info(
        f"[follow_up] Checking last tables: {len(last_tables) if last_tables else 0} tables"
    )
    if not last_tables:
        logger.warning("[follow_up] No previous tables found, returning error")
        raise MissingContextException(
            "No previous query context found. Please ask your initial question first before asking follow-up questions."
        )

    logger.info(f"[follow_up] Creating modified SQL at {time.time() - start_time:.2f}s")
    logger.info(f"[follow_up] Using {len(last_tables)} cached tables")

    try:
        sql_start = time.time()
        sql_response, desc = await _sql_creator.create_sql(
            question=modification,
            list_tables=last_tables,
            temperature=temperature,
            max_tokens=max_tokens,
            follow_up=True,
            sql_prev=prev_sql,
        )
        sql_duration = time.time() - sql_start
        logger.info(f"[follow_up] SQL creation completed in {sql_duration:.2f}s")
        logger.info(f"[follow_up] SQL response type: {type(sql_response)}")
        logger.info(f"[follow_up] SQL response preview: {str(sql_response)[:200]}...")
    except Exception as e:
        logger.error(f"[follow_up] SQL creation failed: {e}")
        logger.exception("[follow_up] Full traceback:")
        raise SQLGenerationException(
            "Failed to modify the previous query. Please try rephrasing your modification request."
        ) from e

    # Parse SQL from response
    logger.info(f"[follow_up] Parsing SQL response at {time.time() - start_time:.2f}s")
    try:
        sql_data = json.loads(sql_response)
        new_sql_query = sql_data["sql_query"]
        logger.info("[follow_up] Successfully parsed JSON response")
    except (json.JSONDecodeError, KeyError) as e:
        new_sql_query = sql_response
        logger.info(f"[follow_up] Using raw response as SQL query (parse error: {e})")

        # Validate that we have something that looks like SQL
        if not new_sql_query or not any(
            keyword in new_sql_query.upper() for keyword in ["SELECT", "WITH"]
        ):
            raise InvalidSQLException(
                "The modified response does not appear to be a valid SQL query."
            )

    logger.info(
        f"[follow_up] New SQL query: {new_sql_query[:200]}..."
        if len(new_sql_query) > 200
        else f"[follow_up] New SQL query: {new_sql_query}"
    )

        # Step: SQL Controller validation/correction
    logger.info(
        f"[follow_up] Starting SQL validation at {time.time() - start_time:.2f}s"
    )

    if _sql_controller:
        try:
    
            logger.info(
                f"[follow_up] Calling SQL controller with query length: {len(new_sql_query)}"
            )

            controller_start = time.time()

            validated_sql = await _sql_controller.control(
                sql_query=new_sql_query,
                user_question=modification,
                table_info=desc,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            controller_duration = time.time() - controller_start

            logger.info(
                f"[follow_up] SQL controller completed in {controller_duration:.2f}s"
            )

            # Check if controller returned empty string (invalid SQL)
            if not validated_sql or not validated_sql.strip():
                logger.warning(
                    "[follow_up] Controller returned empty SQL - query cannot be answered with SELECT"
                )
                raise InvalidSQLException(
                    "The question cannot be answered with a read-only SQL query."
                )

            new_sql_query = validated_sql

        except InvalidSQLException:
            raise
        except Exception as e:
            logger.error(f"[follow_up] SQL controller failed: {e}")
            logger.exception("[follow_up] Controller traceback:")
            logger.warning(
                "[follow_up] Using original SQL after controller failure"
            )
    else:
        logger.warning(
            "[follow_up] SQL controller not initialized, skipping validation"
        )

    logger.info(
        f"[follow_up] Executing new SQL query at {time.time() - start_time:.2f}s"
    )
    try:
        exec_start = time.time()
        df = await _executor.query(new_sql_query)
        exec_duration = time.time() - exec_start
        logger.info(f"[follow_up] SQL execution completed in {exec_duration:.2f}s")
        logger.info(f"[follow_up] Result DataFrame shape: {df.shape}")
    except Exception as e:
        logger.error(f"[follow_up] SQL execution failed: {e}")
        logger.exception("[follow_up] Full traceback:")

        # Check for specific SQL errors
        error_msg = str(e).lower()
        if "syntax" in error_msg:
            raise SQLExecutionException(
                "The modified SQL query has a syntax error. Please try rephrasing your modification."
            ) from e
        elif "permission" in error_msg or "denied" in error_msg:
            raise SQLExecutionException(
                "Database access denied. Please contact your administrator."
            ) from e
        elif "timeout" in error_msg or "timed out" in error_msg:
            raise SQLExecutionException(
                "The modified query took too long to execute. Please try a simpler modification."
            ) from e
        else:
            raise SQLExecutionException(
                "Failed to execute the modified query. Please try again or rephrase your modification."
            ) from e

    logger.info(
        f"[follow_up] Converting DataFrame to markdown at {time.time() - start_time:.2f}s"
    )
    md = df.to_markdown(index=False, numalign="right", stralign="left")
    logger.info(f"[follow_up] Markdown table length: {len(md)}")

    logger.info(
        f"[follow_up] Preparing messages for chat model at {time.time() - start_time:.2f}s"
    )
    messages = [
        SystemMessage(content=SYSTEM_FOLLOW_UP_PROMPT),
        HumanMessage(
            content=f"User question: {modification}\n\nResult of sql query: {md}"
        ),
        AIMessage(content=new_sql_query),
    ]
    logger.info(f"[follow_up] Created {len(messages)} messages for chat model")

    logger.info(f"[follow_up] Invoking chat model at {time.time() - start_time:.2f}s")
    try:
        chat_start = time.time()
        response = await _chat_model.ainvoke(messages)
        chat_duration = time.time() - chat_start
        logger.info(f"[follow_up] Chat model completed in {chat_duration:.2f}s")
        logger.info(f"[follow_up] Response content length: {len(response.content)}")
    except Exception as e:
        logger.error(f"[follow_up] Chat model invocation failed: {e}")
        logger.exception("[follow_up] Full traceback:")
        raise DataConversionException(
            "Failed to generate a natural language response. Please try again."
        ) from e

    result = {
        "content": response.content,
        "type": "text",
        "error": "",
    }

    total_time = time.time() - start_time
    logger.info(f"[follow_up] Completed successfully in {total_time:.2f}s")
    logger.info(
        f"[follow_up] Returning result with content length: {len(response.content)}"
    )
    return result
