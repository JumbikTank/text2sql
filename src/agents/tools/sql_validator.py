"""SQL validation and self-correction utilities.

Inspired by Vanna.ai's approach:
1. Validate SQL syntax with sqlglot
2. If execution fails, feed error back to LLM for correction
"""

import re
import sqlglot
from sqlglot.errors import ParseError
from dataclasses import dataclass
from difflib import get_close_matches


@dataclass
class ValidationResult:
    """Result of SQL validation."""

    if_valid: bool
    error_message: str | None = None
    error_line: int | None = None


def is_sql_valid(sql: str, dialect: str = "postgres") -> ValidationResult:
    """Check if SQL is syntactically valid using sqlglot.

    Args:
        sql: SQL query string
        dialect: SQL dialect (postgres, mysql, sqlite, etc.)

    Returns:
        ValidationResult with validation status and error details
    """
    if not sql or not sql.strip():
        return ValidationResult(
            if_valid=False,
            error_message="Empty SQL query",
        )

    try:
        # Parse with specified dialect for strict validation
        parsed = sqlglot.parse(sql, dialect=dialect)

        # Check if parsing produced any statements
        if not parsed or all(stmt is None for stmt in parsed):
            return ValidationResult(
                if_valid=False,
                error_message="Failed to parse SQL - no valid statements found",
            )

        return ValidationResult(if_valid=True)

    except ParseError as e:
        # Extract error details
        error_msg = str(e)
        error_line = None

        # Try to extract line number from error
        if "line" in error_msg.lower():
            import re

            line_match = re.search(r"line\s*(\d+)", error_msg, re.IGNORECASE)
            if line_match:
                error_line = int(line_match.group(1))

        return ValidationResult(
            if_valid=False,
            error_message=error_msg,
            error_line=error_line,
        )
    except Exception as e:
        return ValidationResult(
            if_valid=False,
            error_message=f"Unexpected validation error: {str(e)}",
        )


def build_correction_prompt(
    original_question: str,
    failed_sql: str,
    error_message: str,
    attempt: int,
    history: list[tuple[str, str]] | None = None,
    relevant_tables: list[dict] | None = None,
    original_evidence: str = "",
) -> str:
    """Build a prompt for LLM to correct failed SQL.

    Args:
        original_question: The user's original question
        failed_sql: The SQL that failed (most recent attempt)
        error_message: Error from the most recent attempt
        attempt: Which retry attempt this is (1, 2, etc.)
        history: Prior (sql, error) pairs from earlier failed attempts
        relevant_tables: List of table dicts (each with `table` and
            `desc_cols`). When provided, column-not-found errors are
            diagnosed against the real schema — the hint tells the model
            which table actually has the column it tried to reference.
        original_evidence: Domain hint that accompanied the question.
            Surfaced as a labelled section so the model can leverage it
            during correction.

    Returns:
        Prompt string for LLM
    """
    hints = _diagnose_postgres_error(error_message, failed_sql, relevant_tables)

    history_block = ""
    if history:
        history_lines = []
        for i, (sql_h, err_h) in enumerate(history, start=1):
            history_lines.append(
                f"--- Prior attempt {i} ---\nSQL:\n{sql_h}\nERROR:\n{err_h}\n"
            )
        history_block = (
            "\nPRIOR FAILED ATTEMPTS (do not repeat the same mistakes):\n"
            + "\n".join(history_lines)
        )

    hints_block = f"\nHINTS:\n{hints}\n" if hints else ""
    evidence_block = f"EVIDENCE: {original_evidence}\n" if original_evidence else ""

    return f"""The previous SQL query failed. Please fix it.

ORIGINAL QUESTION: {original_question}
{evidence_block}{history_block}
LATEST FAILED SQL (attempt {attempt}):
{failed_sql}

ERROR:
{error_message}
{hints_block}
Generate a corrected PostgreSQL query that fixes this error. Make a real
structural change — do not produce the same broken pattern again.
Return ONLY the corrected SQL in JSON format: {{"sql_query": "..."}}
"""


def _diagnose_postgres_error(
    error_message: str,
    failed_sql: str | None = None,
    relevant_tables: list[dict] | None = None,
) -> str:
    """Heuristic hints for common Postgres errors so the LLM can target the
    actual root cause instead of regenerating the same broken pattern.

    For column-not-found / table-not-found errors, when `failed_sql` and
    `relevant_tables` are provided we parse the bad reference out of the
    error message and tell the model exactly which table (if any) really
    owns the column the SQL tried to use.
    """
    msg = error_message.lower()
    hints: list[str] = []

    if "must appear in the group by" in msg or "groupingerror" in msg:
        hints.append(
            "- GROUP BY error: every non-aggregated SELECT/HAVING column must "
            "appear in GROUP BY, or be wrapped in an aggregate. Move "
            "per-row filters into the WHERE/JOIN clauses, push subquery "
            "ordering/limits inside their own SELECT, or wrap referenced "
            "columns with MAX/MIN."
        )
    if "subquery" in msg and ("order by" in msg or "limit" in msg):
        hints.append(
            "- A subquery with ORDER BY+LIMIT cannot be correlated this "
            "deeply; consider a LATERAL join or a windowed CTE."
        )
    if "column" in msg and "does not exist" in msg:
        hints.append(_column_not_found_hint(
            error_message, failed_sql, relevant_tables
        ))
    if "relation" in msg and "does not exist" in msg:
        hints.append(_relation_not_found_hint(
            error_message, relevant_tables
        ))
    if "operator does not exist" in msg:
        hints.append(
            "- Operator/type mismatch: cast operands explicitly (e.g. "
            "::text, ::numeric) or pick a comparable type."
        )
    if "function pg_catalog.extract(unknown, text)" in msg:
        hints.append(
            "- EXTRACT() on a text column: the column is stored as TEXT, "
            "not DATE/TIMESTAMP. Cast it first, e.g. "
            "EXTRACT(YEAR FROM CAST(col AS DATE)) or use "
            "SUBSTRING(col, 1, 4) for 'YYYY-MM-DD' strings."
        )
    if "syntax error" in msg:
        hints.append(
            "- Syntax error: re-check parentheses, commas, and that all "
            "JOINs have an ON clause."
        )

    return "\n".join(h for h in hints if h)


# --- Column- / table-not-found targeted diagnostics ---------------------


# Extracts the bad reference from messages like:
#   column "x" does not exist
#   column pa.player_name does not exist
#   column t1.first_date does not exist
_COL_NOT_FOUND_RE = re.compile(
    r'column\s+"?([\w.]+)"?\s+does not exist', re.IGNORECASE
)
_REL_NOT_FOUND_RE = re.compile(
    r'relation\s+"?([\w.]+)"?\s+does not exist', re.IGNORECASE
)
# Matches table-alias declarations in the SQL: `tablename AS alias`
# or `tablename alias`. Bare table refs without alias also count
# (alias == table itself).
_ALIAS_RE = re.compile(
    r'\b(?:from|join)\s+"?([\w]+)"?(?:\s+as)?\s+(?!where|join|on|inner|left|right|full|outer|group|order|having|limit|union|select)([\w]+)\b',
    re.IGNORECASE,
)


def _extract_aliases(sql: str) -> dict[str, str]:
    """Return `{alias_lower: table_lower}` from FROM/JOIN clauses."""
    aliases: dict[str, str] = {}
    for m in _ALIAS_RE.finditer(sql):
        table, alias = m.group(1), m.group(2)
        aliases[alias.lower()] = table.lower()
        # Bare table refs are usable as their own alias.
        aliases[table.lower()] = table.lower()
    return aliases


def _table_columns(table: dict) -> list[str]:
    """Pull plain column names out of a relevant-table dict.
    `desc_cols` looks like 'id (bigint), name (text), … | values: …'.
    """
    raw = table.get("desc_cols") or table.get("full_desc") or ""
    # Strip the value-hints tail beyond '|', then parse 'name (type)' pairs.
    head = raw.split("|", 1)[0]
    out: list[str] = []
    for part in head.split(","):
        part = part.strip()
        if not part:
            continue
        # name may contain spaces (e.g. "Examination Date (date)").
        paren = part.find(" (")
        if paren > 0:
            name = part[:paren]
        else:
            name = part.split()[0]
        if name:
            out.append(name)
    return out


def _column_not_found_hint(
    error_message: str,
    failed_sql: str | None,
    relevant_tables: list[dict] | None,
) -> str:
    """Build a column-not-found hint that names the *actual* owning table
    when we can find one, or surfaces close-name matches (handles
    case-folded names like `firstDate` ↔ `first_date` and spaced names
    like `"First Date"`)."""
    fallback = (
        "- Column does not exist: re-check the schema, including alias "
        "qualifiers, and don't invent column names."
    )

    m = _COL_NOT_FOUND_RE.search(error_message)
    if not m:
        return fallback
    bad_ref = m.group(1)
    if "." in bad_ref:
        alias, col = bad_ref.split(".", 1)
    else:
        alias, col = "", bad_ref
    col_norm = col.lower().replace('"', "")

    if not relevant_tables:
        return f"- Column `{bad_ref}` does not exist. " + fallback

    # Build a map from each table's column (lower-cased) → table name +
    # original column name (preserves quoting requirements).
    col_to_tables: dict[str, list[tuple[str, str]]] = {}
    all_cols_by_table: dict[str, list[str]] = {}
    for t in relevant_tables:
        tname = (t.get("table") or t.get("text") or "").lower()
        cols = _table_columns(t)
        all_cols_by_table[tname] = cols
        for c in cols:
            col_to_tables.setdefault(c.lower(), []).append((tname, c))

    # 1) Exact match — column name exists, just on a different table.
    if col_norm in col_to_tables:
        owners = col_to_tables[col_norm]
        owner_str = ", ".join(f"`{tn}`.`{cn}`" for tn, cn in owners)
        # Did the model put it on the wrong alias?
        aliases = _extract_aliases(failed_sql or "")
        bound_table = aliases.get(alias.lower(), "") if alias else ""
        if bound_table and bound_table not in {tn for tn, _ in owners}:
            return (
                f"- Column `{col}` is NOT on `{bound_table}` (aliased "
                f"as `{alias}`). It actually lives on: {owner_str}. "
                f"Adjust your JOIN or alias to pull `{col}` from the "
                f"right table."
            )
        return (
            f"- Column `{col}` lives on: {owner_str}. Make sure your "
            f"alias points at one of those tables."
        )

    # 2) Close-name match — handles case / underscore / spacing drift.
    flat_cols = [c for cs in all_cols_by_table.values() for c in cs]
    candidates = get_close_matches(col, flat_cols, n=3, cutoff=0.7)
    if not candidates:
        candidates = get_close_matches(
            col_norm,
            [c.lower() for c in flat_cols],
            n=3, cutoff=0.7,
        )
    if candidates:
        # If a candidate has spaces or mixed case, the model must
        # double-quote it in PostgreSQL.
        suggestions = []
        for cand in candidates:
            owners = col_to_tables.get(cand.lower(), [])
            needs_quote = (" " in cand) or (cand != cand.lower())
            disp = f'"{cand}"' if needs_quote else cand
            owner_part = ""
            if owners:
                owner_part = " (on " + ", ".join(t for t, _ in owners) + ")"
            suggestions.append(f"{disp}{owner_part}")
        quote_hint = ""
        if any((" " in s) or (s != s.lower()) for s in candidates):
            quote_hint = (
                " Names with spaces or mixed case MUST be wrapped in "
                'double quotes, e.g. `"Examination Date"`.'
            )
        return (
            f"- Column `{col}` does not exist. Did you mean: "
            + "; ".join(suggestions)
            + f"?{quote_hint}"
        )

    # 3) Nothing close — list what IS available on the alias's table.
    aliases = _extract_aliases(failed_sql or "")
    bound = aliases.get(alias.lower(), "") if alias else ""
    if bound and bound in all_cols_by_table:
        return (
            f"- Column `{col}` does not exist on `{bound}` (aliased "
            f"`{alias}`). Available columns there: "
            + ", ".join(all_cols_by_table[bound][:30])
            + "."
        )
    return f"- Column `{bad_ref}` does not exist. " + fallback


def _relation_not_found_hint(
    error_message: str, relevant_tables: list[dict] | None
) -> str:
    """Surface the actual table list when the model invents a table name."""
    fallback = (
        "- Relation does not exist: only use tables that appear in the "
        "provided schema."
    )
    m = _REL_NOT_FOUND_RE.search(error_message)
    if not m or not relevant_tables:
        return fallback
    bad = m.group(1).split(".")[-1].lower()
    table_names = [
        (t.get("table") or t.get("text") or "").lower()
        for t in relevant_tables
    ]
    table_names = [t for t in table_names if t]
    candidates = get_close_matches(bad, table_names, n=3, cutoff=0.6)
    if candidates:
        return (
            f"- Table `{bad}` does not exist. Did you mean: "
            + ", ".join(f"`{c}`" for c in candidates)
            + "?"
        )
    return (
        fallback
        + " Available tables: "
        + ", ".join(f"`{t}`" for t in table_names)
    )


def extract_sql_from_response(response: str) -> str | None:
    """Extract SQL from LLM response, handling various formats.

    Args:
        response: Raw LLM response

    Returns:
        Extracted SQL string or None if not found
    """
    import json
    import re

    response = response.strip()

    # Try JSON format first
    try:
        data = json.loads(response)
        if isinstance(data, dict) and "sql_query" in data:
            return data["sql_query"]
    except json.JSONDecodeError:
        pass

    # Try to find JSON in response
    json_match = re.search(r'\{[^{}]*"sql_query"\s*:\s*"([^"]*)"[^{}]*\}', response)
    if json_match:
        return json_match.group(1)

    # Try markdown code block
    code_block_match = re.search(r"```(?:sql)?\s*([\s\S]*?)```", response)
    if code_block_match:
        return code_block_match.group(1).strip()

    # If starts with SELECT/WITH, assume it's raw SQL
    if response.upper().startswith(("SELECT", "WITH")):
        return response

    return None
