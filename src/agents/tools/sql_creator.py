import re
from src.agents.tools.prompt_templates import (
    SYSTEM_PROMPT,
    REVIEWER_RPOMPT,
    FOLLOW_UP_PROMPT,
)


CORRECTION_PROMPT = """You are an expert PostgreSQL debugger.
You will be given:
1. The schema of the relevant tables.
2. The user's original question.
3. One or more prior SQL attempts that FAILED, with their database errors.
4. Optional hints about the class of error.

Your job is to produce a corrected PostgreSQL SELECT query that:
- Actually fixes the root cause of the error (do not produce a near-copy of
  the previous query).
- Is read-only (SELECT/CTE only).
- Uses only columns and tables present in the schema.

When the error is a Postgres GROUP BY error
("must appear in the GROUP BY clause or be used in an aggregate function"):
- Move per-row filters and per-group lookups out of the SELECT/HAVING and
  into a subquery or CTE that does its own aggregation.
- A correlated subquery cannot reference the outer query's grouping
  columns inside ORDER BY/LIMIT — pull the ranking into a windowed CTE
  (ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)) and filter on it.
- Wrap any non-grouped column referenced in HAVING with MAX/MIN, or move
  the comparison into a derived table.

Output exactly one JSON object: {"sql_query": "<corrected SELECT>"}.
"""
from src.agents.table_relationships import TABLE_DEPENDENCIES
from src.agents.tools.column_validator import (
    validate_columns,
    ValidationResult,
    format_validation_error,
)
import pandas as pd
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage


# Custom exceptions for SQL Creator
class SQLCreatorException(Exception):
    """Base exception for SQL Creator errors"""

    pass


class ColumnValidationError(SQLCreatorException):
    """Exception raised when generated SQL has invalid column references"""

    def __init__(self, message: str, validation_result: ValidationResult):
        super().__init__(message)
        self.validation_result = validation_result


class SQLGuardrailException(SQLCreatorException):
    """Exception raised when SQL violates safety guardrails"""

    pass


class SQLReviewException(SQLCreatorException):
    """Exception raised when SQL review fails"""

    pass


class TableRenderingException(SQLCreatorException):
    """Exception raised when table rendering fails"""

    pass


class LLMInvocationException(SQLCreatorException):
    """Exception raised when LLM invocation fails"""

    pass


READ_ONLY_DENYLIST = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|MERGE|CREATE\s+TABLE|CREATE\s+INDEX)\b",
    re.IGNORECASE,
)


class SQLCreator:
    def __init__(
        self,
        *,
        chat_model: BaseChatModel,
        desc_data,
    ) -> None:
        self.chat_model = chat_model
        self.desc_data = desc_data

    @staticmethod
    def _render_tables(
        list_tables: list[dict[int, str, float, str, str, str]], desc_data: pd.DataFrame
    ) -> str:
        try:
            desc = ""
            for i, table in enumerate(list_tables, start=1):
                if "full_desc" not in table or "desc_cols" not in table:
                    raise TableRenderingException(
                        f"Table {i} missing required fields 'full_desc' or 'desc_cols'"
                    )
                desc += f"{table['full_desc']}\n\n{table['desc_cols']}\n\n"

            # Add relationship information if available
            table_name = table.get("table", "").lower()
            if table_name in TABLE_DEPENDENCIES:
                relationships = TABLE_DEPENDENCIES[table_name]
                desc += "Table reletionships:\n"
                for column_desc, related_table, column_rel in relationships:
                    desc += f"{table_name} - {column_desc} -> can be joined with {related_table} + {column_rel}\n"
                desc += "\n\n"

            used_tables = []

            for table in list_tables:
                if table_name in TABLE_DEPENDENCIES and table_name not in used_tables:
                    # print(TABLE_DEPENDENCIES[table_name])
                    desc += (
                        desc_data[
                            desc_data["TABLE"]
                            == TABLE_DEPENDENCIES[table_name][0][1].upper()
                        ]["FULL_DESC"].values[0]
                        + "\n\n"
                    )
                    used_tables.append(TABLE_DEPENDENCIES[table_name][0][1])
            return desc
        except KeyError as e:
            raise TableRenderingException(
                f"Error rendering tables - missing expected key: {e}"
            ) from e
        except Exception as e:
            raise TableRenderingException(
                f"Unexpected error while rendering tables: {e}"
            ) from e

    @staticmethod
    def _guardrails(sql: str) -> None:
        if READ_ONLY_DENYLIST.search(sql):
            match = READ_ONLY_DENYLIST.search(sql)
            raise SQLGuardrailException(
                f"Generated SQL contains disallowed statement '{match.group()}'. "
                "Only read-only queries are permitted (SELECT statements)."
            )

    @staticmethod
    def _render_examples(examples: list[dict] | None) -> str:
        """Render retrieved Q-SQL pairs as a labelled examples block.

        Each example dict needs at minimum `question` and `sql` keys;
        `evidence`, `db_id`, and `score` are optional. Examples are
        framed as analogous prior queries from OTHER databases — the
        model is told to copy *idioms and structure*, not table/column
        names. Each example carries its source `db_id` so the gap to
        the test schema is visible.
        """
        if not examples:
            return ""
        lines = [
            "Reference examples (analogous queries from DIFFERENT "
            "databases, included for SQL-style guidance only):",
            "",
            "IMPORTANT: each example's table and column names belong to "
            "a DIFFERENT database than the one you must query. DO NOT "
            "copy any table or column name from these examples into your "
            "answer. Use ONLY the tables and columns shown in the "
            "Schema section above. Copy the structural patterns "
            "(CAST/NULLIF for ratios, JOIN ordering, GROUP BY/HAVING, "
            "subqueries, BIRD-style idioms) — never the names.",
        ]
        for i, ex in enumerate(examples, start=1):
            q = ex.get("question", "").strip()
            sql = ex.get("sql", "").strip()
            ev = (ex.get("evidence") or "").strip()
            db_id = (ex.get("db_id") or "").strip()
            if not q or not sql:
                continue
            header = f"--- Example {i}"
            if db_id:
                header += f" (from db_id={db_id} — NOT your test database)"
            header += " ---"
            lines.append(header)
            lines.append(f"Question: {q}")
            if ev:
                lines.append(f"Evidence: {ev}")
            lines.append(f"SQL: {sql}")
        return "\n".join(lines)

    async def create_sql(
        self,
        *,
        question: str,
        list_tables: list[str],
        evidence: str = "",
        examples: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        follow_up: bool = False,
        sql_prev: str = "",
        validate_columns_flag: bool = True,
        max_validation_retries: int = 2,
        correction_mode: bool = False,
    ) -> tuple[str, str]:
        desc = self._render_tables(list_tables, self.desc_data)
        evidence_block = f"\n\nEvidence: {evidence}" if evidence else ""
        examples_block = self._render_examples(examples)
        examples_section = f"\n\n{examples_block}" if examples_block else ""

        if correction_mode:
            # In correction mode the caller supplies the failing SQL +
            # error in `question` (already built by build_correction_prompt,
            # which includes its own EVIDENCE section if present).
            prompt = "Schema:\n" + desc + "\n\n" + question
            messages = [
                SystemMessage(content=CORRECTION_PROMPT),
                HumanMessage(content=prompt),
            ]
        elif follow_up:
            prompt = (
                "Schema:\n" + desc + "\n\n"
                f"Question: {question}{evidence_block}\n\n"
                f"SQL query:{sql_prev}"
            )
            messages = [
                SystemMessage(content=FOLLOW_UP_PROMPT),
                HumanMessage(content=prompt),
            ]
        else:
            prompt = (
                "Schema:\n" + desc + examples_section + "\n\n"
                f"Question: {question}{evidence_block}"
            )
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]

        try:
            resp = await self.chat_model.ainvoke(
                messages,
                # temperature=0.0,
                max_tokens=max_tokens,
                # top_p=1.0,
                # top_k=1,
                # seed=42,
            )
        except Exception as e:
            raise LLMInvocationException(
                f"Failed to generate SQL query from LLM: {str(e)}"
            ) from e

        sql = resp.content.strip()

        try:
            self._guardrails(sql)
        except SQLGuardrailException as e:
            print(f"SQL guardrails failed: {e}")
            try:
                sql = await self._reviewer(sql, question, temperature, max_tokens)
                self._guardrails(sql)
            except SQLGuardrailException as review_guard_error:
                print(f"SQL review still violates guardrails: {review_guard_error}")
                raise SQLGuardrailException(
                    f"Generated SQL violates safety rules even after review: {e}"
                ) from review_guard_error
            except Exception as review_error:
                print(f"SQL review failed: {review_error}")
                raise SQLReviewException(
                    f"Failed to review and fix SQL query: {review_error}"
                ) from review_error

        # Column validation with self-correction
        if validate_columns_flag:
            sql = await self._validate_and_fix_columns(
                sql=sql,
                question=question,
                list_tables=list_tables,
                desc=desc,
                max_retries=max_validation_retries,
                max_tokens=max_tokens,
            )

        return sql, desc

    async def _validate_and_fix_columns(
        self,
        sql: str,
        question: str,
        list_tables: list[dict],
        desc: str,
        max_retries: int = 2,
        max_tokens: int = 1024,
    ) -> str:
        """Validate column references and attempt to fix if invalid.

        Args:
            sql: Generated SQL query
            question: Original user question
            list_tables: List of table dicts with schema info
            desc: Rendered table descriptions
            max_retries: Maximum correction attempts
            max_tokens: Max tokens for LLM calls

        Returns:
            Validated (possibly corrected) SQL query

        Raises:
            ColumnValidationError: If validation fails after all retries
        """
        current_sql = sql

        for attempt in range(max_retries + 1):
            # Validate columns
            validation_result = validate_columns(
                sql=current_sql,
                tables=list_tables,
                strict=False,  # Don't fail on unknown tables/aliases
            )

            if validation_result.if_valid:
                if attempt > 0:
                    print(f"Column validation passed after {attempt} correction(s)")
                return current_sql

            # First attempt - just log the issue
            error_msg = format_validation_error(validation_result)
            print(f"Column validation failed (attempt {attempt + 1}):\n{error_msg}")

            # Last attempt - raise error
            if attempt >= max_retries:
                print(f"Column validation failed after {max_retries} retries")
                # Return SQL anyway with warning - don't block user
                # The SQL executor will catch the actual error
                return current_sql

            # Try to fix with LLM
            correction_prompt = validation_result.get_correction_prompt()
            current_sql = await self._fix_column_references(
                sql=current_sql,
                question=question,
                desc=desc,
                correction_prompt=correction_prompt,
                max_tokens=max_tokens,
            )

            # Validate guardrails on corrected SQL
            try:
                self._guardrails(current_sql)
            except SQLGuardrailException:
                # If correction broke safety, revert to original
                print("Corrected SQL violates guardrails, reverting")
                return sql

        return current_sql

    async def _fix_column_references(
        self,
        sql: str,
        question: str,
        desc: str,
        correction_prompt: str,
        max_tokens: int = 1024,
    ) -> str:
        """Use LLM to fix invalid column references.

        Args:
            sql: SQL with invalid columns
            question: Original user question
            desc: Table schema descriptions
            correction_prompt: Prompt explaining the errors
            max_tokens: Max tokens for response

        Returns:
            Corrected SQL query
        """
        system_prompt = """You are a SQL correction assistant. Fix the invalid column references in the SQL query.
Use ONLY the exact column names from the schema provided.

IMPORTANT:
- Match column names EXACTLY as they appear in the schema
- Do not invent or assume column names
- If a column doesn't exist, use the closest valid column from the schema
- Return ONLY the corrected SQL query, no explanations"""

        user_prompt = f"""Original question: {question}

Schema information:
{desc}

SQL with errors:
{sql}

{correction_prompt}

Return the corrected SQL query:"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            resp = await self.chat_model.ainvoke(
                messages,
                max_tokens=max_tokens,
            )
            corrected_sql = resp.content.strip()

            # Clean up response (remove markdown code blocks if present)
            if corrected_sql.startswith("```"):
                lines = corrected_sql.split("\n")
                # Remove first line (```sql) and last line (```)
                corrected_sql = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            return corrected_sql
        except Exception as e:
            print(f"Failed to fix column references: {e}")
            return sql  # Return original on failure

    async def _reviewer(
        self,
        sql: str,
        question: str,
        temperature: float = 0.8,
        max_tokens: int = 8192,
        max_retry: int = 3,
    ) -> str:
        new_sql = sql

        prompt = f"User question: {question}\n\nSQL query with bug:\n{sql}"

        for attempt in range(max_retry):
            try:
                messages = [
                    SystemMessage(content=REVIEWER_RPOMPT),
                    HumanMessage(content=prompt),
                ]

                try:
                    resp = await self.chat_model.ainvoke(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        # top_p = 1,
                        # top_k = 1,
                        # seed = 42
                    )
                except Exception as e:
                    raise LLMInvocationException(
                        f"Failed to invoke LLM for SQL review: {str(e)}"
                    ) from e

                new_sql = resp.content.strip()
                self._guardrails(new_sql)
                print(f"SQL review successful on attempt {attempt + 1}")
                break

            except SQLGuardrailException as e:
                print(f"Review attempt {attempt + 1} failed guardrails: {e}")
                if attempt == max_retry - 1:
                    print("All review attempts failed")
                    raise SQLReviewException(
                        f"Could not generate safe SQL after {max_retry} attempts. "
                        f"Last error: {e}"
                    )
                continue
            except Exception as e:
                print(f"Unexpected error during review: {e}")
                raise

        return new_sql
