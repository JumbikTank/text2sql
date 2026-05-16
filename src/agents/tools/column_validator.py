"""Column validation for generated SQL queries.

Validates that column references in SQL match actual schema columns.
Catches hallucinations like 'category.name' when actual column is 'category.category'.
"""

import re
from dataclasses import dataclass
from difflib import get_close_matches


class ColumnValidationException(Exception):
    """Exception raised when column validation fails."""


@dataclass
class ColumnMismatch:
    """Represents a column reference that doesn't match schema."""

    table: str
    invalid_column: str
    suggestions: list[str]


@dataclass
class ValidationResult:
    """Result of column validation."""

    if_valid: bool
    mismatches: list[ColumnMismatch]
    error_message: str | None = None

    def get_correction_prompt(self) -> str:
        """Generate a prompt for LLM to fix the SQL."""
        if self.if_valid:
            return ""

        lines = ["The generated SQL has invalid column references:\n"]
        for m in self.mismatches:
            if m.suggestions:
                lines.append(
                    f"- '{m.table}.{m.invalid_column}' does not exist. "
                    f"Did you mean: {', '.join(m.suggestions)}?"
                )
            else:
                lines.append(
                    f"- '{m.table}.{m.invalid_column}' does not exist in table '{m.table}'."
                )

        lines.append("\nPlease correct the column names and regenerate the SQL.")
        return "\n".join(lines)


def parse_column_info(columns_info: str) -> set[str]:
    """Extract column names from the columns_info string.

    Args:
        columns_info: String like "id (integer), name (varchar), created_at (timestamp)"

    Returns:
        Set of column names (lowercase)
    """
    if not columns_info:
        return set()

    # Pattern: column_name (data_type)
    # Handles: "id (integer)", "first_name (character varying)"
    pattern = r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]+\)"
    matches = re.findall(pattern, columns_info)
    return {col.lower() for col in matches}


def extract_table_columns_from_schema(
    tables: list[dict],
) -> dict[str, set[str]]:
    """Build a mapping of table -> columns from schema data.

    Args:
        tables: List of table dicts with 'table' and 'desc_cols' keys

    Returns:
        Dict mapping table names (lowercase) to set of column names (lowercase)
    """
    schema = {}
    for table in tables:
        table_name = table.get("table", "").lower()
        columns_info = table.get("desc_cols", "")

        if table_name:
            schema[table_name] = parse_column_info(columns_info)

    return schema


def extract_sql_column_references(sql: str) -> list[tuple[str, str]]:
    """Extract table.column references from SQL.

    Args:
        sql: SQL query string

    Returns:
        List of (table_alias, column_name) tuples
    """
    references = []

    # Pattern for table.column or alias.column references
    # Matches: t.column_name, table_name.column, c.first_name
    # Excludes: function calls like COUNT(*), string literals
    pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*?)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"

    # Find all matches
    for match in re.finditer(pattern, sql, re.IGNORECASE):
        table_ref = match.group(1).lower()
        column_ref = match.group(2).lower()

        # Skip common SQL keywords that might be false positives
        skip_prefixes = {"pg_", "information_", "sql_"}
        if any(table_ref.startswith(p) for p in skip_prefixes):
            continue

        references.append((table_ref, column_ref))

    return references


def resolve_table_alias(
    alias: str,
    sql: str,
    schema: dict[str, set[str]],
) -> str | None:
    """Resolve a table alias to the actual table name.

    Args:
        alias: The alias used in SQL (e.g., 'c', 'f')
        sql: The full SQL query
        schema: Dict of actual table names -> columns

    Returns:
        Actual table name if resolved, None otherwise
    """
    # Already a real table name?
    if alias in schema:
        return alias

    # Pattern to find: FROM table_name alias or JOIN table_name alias
    # Also handles: FROM table_name AS alias
    patterns = [
        rf"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:AS\s+)?{re.escape(alias)}\b",
        rf"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:AS\s+)?{re.escape(alias)}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, sql, re.IGNORECASE)
        if match:
            table_name = match.group(1).lower()
            if table_name in schema:
                return table_name

    return None


def validate_columns(
    sql: str,
    tables: list[dict],
    strict: bool = True,
) -> ValidationResult:
    """Validate that column references in SQL match actual schema.

    Args:
        sql: Generated SQL query
        tables: List of table dicts with schema info
        strict: If True, unknown tables fail validation. If False, skip them.

    Returns:
        ValidationResult with validation status and any mismatches
    """
    # Build schema mapping
    schema = extract_table_columns_from_schema(tables)

    if not schema:
        return ValidationResult(
            if_valid=True,
            mismatches=[],
            error_message="No schema information available for validation",
        )

    # Extract column references from SQL
    references = extract_sql_column_references(sql)

    mismatches = []

    for table_ref, column_ref in references:
        # Resolve alias to actual table name
        actual_table = resolve_table_alias(table_ref, sql, schema)

        if actual_table is None:
            # Unknown table/alias
            if strict:
                # Try to find closest table name
                closest_tables = get_close_matches(
                    table_ref, list(schema.keys()), n=2, cutoff=0.6
                )
                mismatches.append(
                    ColumnMismatch(
                        table=table_ref,
                        invalid_column=column_ref,
                        suggestions=[f"Table '{t}' exists" for t in closest_tables]
                        if closest_tables
                        else [],
                    )
                )
            continue

        # Get columns for this table
        valid_columns = schema.get(actual_table, set())

        if not valid_columns:
            continue

        # Check if column exists
        if column_ref not in valid_columns:
            # Find suggestions using fuzzy matching
            suggestions = get_close_matches(
                column_ref, list(valid_columns), n=3, cutoff=0.5
            )

            mismatches.append(
                ColumnMismatch(
                    table=actual_table,
                    invalid_column=column_ref,
                    suggestions=suggestions,
                )
            )

    return ValidationResult(
        if_valid=len(mismatches) == 0,
        mismatches=mismatches,
        error_message=None if len(mismatches) == 0 else f"Found {len(mismatches)} invalid column reference(s)",
    )


def format_validation_error(result: ValidationResult) -> str:
    """Format validation errors for user-friendly output.

    Args:
        result: ValidationResult from validate_columns()

    Returns:
        Formatted error string
    """
    if result.if_valid:
        return ""

    lines = ["SQL validation failed - invalid column references:\n"]

    for mismatch in result.mismatches:
        line = f"  • '{mismatch.table}.{mismatch.invalid_column}' - column not found"
        if mismatch.suggestions:
            line += f"\n    Suggestions: {', '.join(mismatch.suggestions)}"
        lines.append(line)

    return "\n".join(lines)
