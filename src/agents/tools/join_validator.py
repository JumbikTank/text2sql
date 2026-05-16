"""JOIN validation for generated SQL queries.

Validates that JOIN conditions use correct foreign key relationships.
Catches issues like:
- Joining through wrong columns (film.film_id = rental.inventory_id)
- Skipping intermediate tables (film -> rental without inventory)
- Using wrong FK relationships (store.manager_staff_id vs staff.store_id)
"""

import re
from dataclasses import dataclass, field


@dataclass
class ForeignKey:
    """Represents a foreign key relationship."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str


@dataclass
class JoinCondition:
    """Represents a parsed JOIN condition from SQL."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    join_type: str  # JOIN, LEFT JOIN, etc.
    raw_condition: str


@dataclass
class JoinIssue:
    """Represents a problematic JOIN condition."""

    join_condition: JoinCondition
    issue_type: str  # "invalid_fk", "wrong_direction", "missing_intermediate"
    message: str
    suggested_path: list[str] = field(default_factory=list)


@dataclass
class JoinValidationResult:
    """Result of JOIN validation."""

    if_valid: bool
    issues: list[JoinIssue]
    error_message: str | None = None

    def get_correction_prompt(self) -> str:
        """Generate a prompt for LLM to fix the JOINs."""
        if self.if_valid:
            return ""

        lines = ["The generated SQL has invalid JOIN conditions:\n"]
        for issue in self.issues:
            lines.append(f"- {issue.message}")
            if issue.suggested_path:
                lines.append(f"  Correct JOIN path: {' -> '.join(issue.suggested_path)}")

        lines.append(
            "\nPlease correct the JOIN conditions using the proper foreign key relationships."
        )
        return "\n".join(lines)


def parse_foreign_keys_from_full_text(full_text: str) -> list[ForeignKey]:
    """Extract foreign key relationships from the full_text field.

    Args:
        full_text: The full_text string from notes table containing FK info
                   Format: "Foreign Keys: col1 -> table1.col1; col2 -> table2.col2"

    Returns:
        List of ForeignKey objects
    """
    fks = []

    # Find the Foreign Keys line
    fk_match = re.search(r"Foreign Keys:\s*(.+?)(?:\n|$)", full_text, re.IGNORECASE)
    if not fk_match:
        return fks

    fk_line = fk_match.group(1)

    # Extract table name from the full_text
    table_match = re.search(r"Table:\s*(\w+)", full_text)
    if not table_match:
        return fks

    source_table = table_match.group(1).lower()

    # Parse each FK relationship: "col -> target_table.target_col"
    # They're separated by semicolons
    fk_pattern = r"(\w+)\s*->\s*(\w+)\.(\w+)"
    for match in re.finditer(fk_pattern, fk_line):
        source_col = match.group(1).lower()
        target_table = match.group(2).lower()
        target_col = match.group(3).lower()

        fks.append(
            ForeignKey(
                source_table=source_table,
                source_column=source_col,
                target_table=target_table,
                target_column=target_col,
            )
        )

    return fks


def build_fk_graph(tables: list[dict]) -> dict[str, list[ForeignKey]]:
    """Build a graph of foreign key relationships from table metadata.

    Args:
        tables: List of table dicts with 'table' and 'full_desc' keys

    Returns:
        Dict mapping table names to list of outgoing FKs
    """
    fk_graph: dict[str, list[ForeignKey]] = {}

    for table in tables:
        table_name = table.get("table", "").lower()
        full_desc = table.get("full_desc", "")

        if table_name:
            fks = parse_foreign_keys_from_full_text(full_desc)
            if fks:
                fk_graph[table_name] = fks

    return fk_graph


def extract_join_conditions(sql: str, schema: dict[str, set[str]]) -> list[JoinCondition]:
    """Extract JOIN conditions from SQL query.

    Args:
        sql: SQL query string
        schema: Dict of table names -> column names for alias resolution

    Returns:
        List of JoinCondition objects
    """
    joins = []

    # Pattern to match JOIN clauses with ON conditions
    # Handles: JOIN table alias ON condition, LEFT JOIN table alias ON condition, etc.
    join_pattern = r"((?:LEFT\s+|RIGHT\s+|INNER\s+|OUTER\s+|FULL\s+)?JOIN)\s+(\w+)\s+(?:AS\s+)?(\w+)?\s+ON\s+([^;]+?)(?=(?:LEFT|RIGHT|INNER|OUTER|FULL)?\s*JOIN|\s*WHERE|\s*GROUP|\s*ORDER|\s*LIMIT|\s*HAVING|\s*$|\s*;)"

    for match in re.finditer(join_pattern, sql, re.IGNORECASE | re.DOTALL):
        join_type = match.group(1).strip().upper()
        joined_table = match.group(2).lower()
        alias = (match.group(3) or joined_table).lower()
        on_condition = match.group(4).strip()

        # Parse the ON condition to extract column references
        # Pattern: alias1.col1 = alias2.col2
        cond_pattern = r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)"
        cond_match = re.search(cond_pattern, on_condition, re.IGNORECASE)

        if cond_match:
            left_alias = cond_match.group(1).lower()
            left_col = cond_match.group(2).lower()
            right_alias = cond_match.group(3).lower()
            right_col = cond_match.group(4).lower()

            # Resolve aliases to actual table names
            left_table = resolve_alias_to_table(left_alias, sql, schema)
            right_table = resolve_alias_to_table(right_alias, sql, schema)

            if left_table and right_table:
                joins.append(
                    JoinCondition(
                        left_table=left_table,
                        left_column=left_col,
                        right_table=right_table,
                        right_column=right_col,
                        join_type=join_type,
                        raw_condition=on_condition.strip(),
                    )
                )

    return joins


def resolve_alias_to_table(
    alias: str, sql: str, schema: dict[str, set[str]]
) -> str | None:
    """Resolve a table alias to actual table name.

    Args:
        alias: The alias used in SQL
        sql: Full SQL query
        schema: Dict of actual table names -> columns

    Returns:
        Actual table name if resolved, None otherwise
    """
    alias = alias.lower()

    # Check if it's already a table name
    if alias in schema:
        return alias

    # Look for FROM table alias or JOIN table alias patterns
    patterns = [
        rf"\bFROM\s+(\w+)\s+(?:AS\s+)?{re.escape(alias)}\b",
        rf"\bJOIN\s+(\w+)\s+(?:AS\s+)?{re.escape(alias)}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, sql, re.IGNORECASE)
        if match:
            table_name = match.group(1).lower()
            if table_name in schema:
                return table_name

    return None


def if_valid_fk_join(
    join: JoinCondition,
    fk_graph: dict[str, list[ForeignKey]],
    schema: dict[str, set[str]] | None = None,
) -> tuple[bool, str | None, str | None]:
    """Check if a JOIN condition matches a valid FK relationship.

    Args:
        join: The JOIN condition to validate
        fk_graph: Graph of FK relationships
        schema: Dict of table names -> columns (for intermediate table detection)

    Returns:
        Tuple of (is_valid, error_message, suggested_intermediate_table)
    """
    left_table = join.left_table
    right_table = join.right_table
    left_col = join.left_column
    right_col = join.right_column

    # Check if left -> right FK exists
    if left_table in fk_graph:
        for fk in fk_graph[left_table]:
            if (
                fk.source_column == left_col
                and fk.target_table == right_table
                and fk.target_column == right_col
            ):
                return True, None, None

    # Check if right -> left FK exists (reverse direction)
    if right_table in fk_graph:
        for fk in fk_graph[right_table]:
            if (
                fk.source_column == right_col
                and fk.target_table == left_table
                and fk.target_column == left_col
            ):
                return True, None, None

    # Check if the columns at least match (same name, common pattern)
    if left_col == right_col and (
        left_col.endswith("_id") or left_col in ("id",)
    ):
        # Matching ID columns - likely valid but not in FK graph
        # This could be a view or missing FK metadata
        return True, None, None

    # Heuristic: detect when columns reference different aspects of same entity
    # E.g., store.manager_staff_id and payment.staff_id both reference staff
    intermediate = _detect_common_reference(
        left_table, left_col, right_table, right_col, schema, fk_graph
    )
    if intermediate:
        return (
            False,
            f"Columns {left_table}.{left_col} and {right_table}.{right_col} "
            f"both reference '{intermediate}' table - join through '{intermediate}' instead",
            intermediate,
        )

    return (
        False,
        f"No FK relationship found between {left_table}.{left_col} and {right_table}.{right_col}",
        None,
    )


def _detect_common_reference(
    left_table: str,
    left_col: str,
    right_table: str,
    right_col: str,
    schema: dict[str, set[str]] | None,
    fk_graph: dict[str, list[ForeignKey]],
) -> str | None:
    """Detect if two columns both reference the same intermediate table.

    E.g., store.manager_staff_id and payment.staff_id both reference staff.

    Args:
        left_table, left_col: Left side of join
        right_table, right_col: Right side of join
        schema: Available table names
        fk_graph: FK relationships

    Returns:
        Name of common intermediate table, or None
    """
    if not schema:
        return None

    # Extract potential table references from column names
    # E.g., "staff_id" -> "staff", "manager_staff_id" -> "staff"
    def extract_table_ref(col: str) -> str | None:
        if col.endswith("_id"):
            # Remove _id suffix
            base = col[:-3]
            # Check for pattern like "manager_staff" -> "staff"
            parts = base.split("_")
            for i in range(len(parts)):
                candidate = "_".join(parts[i:])
                if candidate in schema:
                    return candidate
            # Also check the base directly
            if base in schema:
                return base
        return None

    left_ref = extract_table_ref(left_col)
    right_ref = extract_table_ref(right_col)

    # If both columns reference the same table, suggest going through it
    if left_ref and right_ref and left_ref == right_ref:
        # Make sure it's not one of the tables already in the join
        if left_ref not in (left_table, right_table):
            return left_ref

    # Check FK graph for common targets
    left_fk_targets = set()
    right_fk_targets = set()

    if left_table in fk_graph:
        for fk in fk_graph[left_table]:
            if fk.source_column == left_col:
                left_fk_targets.add(fk.target_table)

    if right_table in fk_graph:
        for fk in fk_graph[right_table]:
            if fk.source_column == right_col:
                right_fk_targets.add(fk.target_table)

    # Find common FK targets
    common = left_fk_targets & right_fk_targets
    if common:
        # Return the first common target that isn't one of the join tables
        for table in common:
            if table not in (left_table, right_table):
                return table

    return None


def find_join_path(
    source_table: str,
    target_table: str,
    fk_graph: dict[str, list[ForeignKey]],
    max_depth: int = 3,
) -> list[str] | None:
    """Find a valid JOIN path between two tables using BFS.

    Args:
        source_table: Starting table
        target_table: Target table
        fk_graph: Graph of FK relationships
        max_depth: Maximum path length to search

    Returns:
        List of table names forming the path, or None if not found
    """
    if source_table == target_table:
        return [source_table]

    # Build reverse FK graph (for bidirectional traversal)
    reverse_graph: dict[str, list[tuple[str, str, str]]] = {}
    for table, fks in fk_graph.items():
        for fk in fks:
            if fk.target_table not in reverse_graph:
                reverse_graph[fk.target_table] = []
            reverse_graph[fk.target_table].append(
                (table, fk.source_column, fk.target_column)
            )

    # BFS
    queue: list[tuple[str, list[str]]] = [(source_table, [source_table])]
    visited = {source_table}

    while queue:
        current, path = queue.pop(0)

        if len(path) > max_depth:
            continue

        # Forward edges (current table has FK to other tables)
        if current in fk_graph:
            for fk in fk_graph[current]:
                next_table = fk.target_table
                if next_table == target_table:
                    return path + [next_table]
                if next_table not in visited:
                    visited.add(next_table)
                    queue.append((next_table, path + [next_table]))

        # Reverse edges (other tables have FK to current table)
        if current in reverse_graph:
            for src_table, _, _ in reverse_graph[current]:
                if src_table == target_table:
                    return path + [src_table]
                if src_table not in visited:
                    visited.add(src_table)
                    queue.append((src_table, path + [src_table]))

    return None


def validate_joins(
    sql: str,
    tables: list[dict],
    strict: bool = False,
) -> JoinValidationResult:
    """Validate JOIN conditions in SQL against schema FK relationships.

    Args:
        sql: Generated SQL query
        tables: List of table dicts with schema info
        strict: If True, require explicit FK for all JOINs. If False, allow matching ID columns.

    Returns:
        JoinValidationResult with validation status and any issues
    """
    # Build schema for alias resolution
    from src.agents.tools.column_validator import extract_table_columns_from_schema

    schema = extract_table_columns_from_schema(tables)

    if not schema:
        return JoinValidationResult(
            if_valid=True,
            issues=[],
            error_message="No schema information available for validation",
        )

    # Build FK graph
    fk_graph = build_fk_graph(tables)

    # Extract JOIN conditions
    joins = extract_join_conditions(sql, schema)

    if not joins:
        return JoinValidationResult(if_valid=True, issues=[])

    issues = []

    for join in joins:
        is_valid, error_msg = if_valid_fk_join(join, fk_graph)

        if not is_valid:
            # Try to find a valid path
            suggested_path = find_join_path(
                join.left_table, join.right_table, fk_graph
            )

            issue_type = "invalid_fk"
            message = (
                f"Invalid JOIN: {join.left_table}.{join.left_column} = "
                f"{join.right_table}.{join.right_column}"
            )

            if suggested_path and len(suggested_path) > 2:
                issue_type = "missing_intermediate"
                intermediate = " -> ".join(suggested_path[1:-1])
                message += f". Missing intermediate table(s): {intermediate}"

            issues.append(
                JoinIssue(
                    join_condition=join,
                    issue_type=issue_type,
                    message=message,
                    suggested_path=suggested_path or [],
                )
            )

    return JoinValidationResult(
        if_valid=len(issues) == 0,
        issues=issues,
        error_message=None if not issues else f"Found {len(issues)} invalid JOIN(s)",
    )


def format_join_validation_error(result: JoinValidationResult) -> str:
    """Format JOIN validation errors for user-friendly output.

    Args:
        result: JoinValidationResult from validate_joins()

    Returns:
        Formatted error string
    """
    if result.if_valid:
        return ""

    lines = ["SQL validation failed - invalid JOIN conditions:\n"]

    for issue in result.issues:
        lines.append(f"  • {issue.message}")
        if issue.suggested_path:
            lines.append(f"    Suggested path: {' -> '.join(issue.suggested_path)}")

    return "\n".join(lines)
