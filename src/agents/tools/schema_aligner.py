"""Schema alignment step (TA-SQL-inspired).

Before generating SQL, force the model to commit to specific
(table, column) pairs for each meaningful phrase in the question.
Aligns the question to the schema *first*, then the SQL generation
step uses that alignment as a structural blueprint.

This addresses three failure modes we saw in regression audits:
  - extra_table:           model adds JOINs it doesn't need
  - extra_columns:         model SELECTs columns the question never asked for
  - wrong_filter_or_value: WHERE references the wrong column

The alignment is validated against the actual schema — every
(table, column) the model proposes must exist. If validation fails,
one retry with the validation error injected. If still invalid we
return None and the SQL creator falls back to its normal behavior.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.common.logger import get_logger

logger = get_logger(__name__)


_ALIGNER_SYSTEM = (
    "You are a schema alignment assistant for text-to-SQL.\n\n"
    "Given a database schema (tables with typed columns and foreign "
    "keys) and a natural-language question, identify which "
    "(table, column) pairs the question references. Do NOT write SQL. "
    "Your job is to map question phrases to exact schema entities.\n\n"
    "Output strict JSON:\n"
    "{\n"
    '  "tables": ["<table_name>", ...],      // ALL tables involved\n'
    '  "select_columns": [                    // columns the question asks to OUTPUT\n'
    '    {"table": "<t>", "column": "<c>"}, ...\n'
    "  ],\n"
    '  "filter_columns": [                    // columns used in WHERE / filter conditions\n'
    '    {"table": "<t>", "column": "<c>", "predicate": "<short description>"}, ...\n'
    "  ],\n"
    '  "aggregate_columns": [                 // columns aggregated (SUM/AVG/MAX/MIN/COUNT)\n'
    '    {"table": "<t>", "column": "<c>", "agg": "<SUM|AVG|MAX|MIN|COUNT>"}, ...\n'
    "  ],\n"
    '  "joins": [                              // join conditions\n'
    '    {"left": "<t1.col>", "right": "<t2.col>"}, ...\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Use ONLY tables and columns that appear in the schema.\n"
    "- Use the EXACT column names from the schema (preserve case, spaces, quotes).\n"
    "- Keep `select_columns` minimal: only what the question explicitly asks for.\n"
    "- If the question is read-only-impossible, return all arrays empty.\n"
    "- Output the JSON object and nothing else."
)


@dataclass
class Alignment:
    """Validated alignment for a single question."""
    tables: list[str] = field(default_factory=list)
    select_columns: list[dict[str, str]] = field(default_factory=list)
    filter_columns: list[dict[str, str]] = field(default_factory=list)
    aggregate_columns: list[dict[str, str]] = field(default_factory=list)
    joins: list[dict[str, str]] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        """Render the alignment as a structured constraint block that
        the SQL creator can read."""
        lines = ["ALIGNMENT PLAN — your SQL must follow this structural plan:"]
        if self.tables:
            lines.append(f"- Tables to use (exactly these): {', '.join(self.tables)}")
        if self.select_columns:
            cols = ", ".join(
                f"{c['table']}.{c['column']}" for c in self.select_columns
            )
            lines.append(f"- SELECT exactly these columns: {cols}")
        if self.filter_columns:
            preds = "; ".join(
                f"{c['table']}.{c['column']} ({c.get('predicate', '?')})"
                for c in self.filter_columns
            )
            lines.append(f"- WHERE on: {preds}")
        if self.aggregate_columns:
            aggs = ", ".join(
                f"{a.get('agg', '?')}({a['table']}.{a['column']})"
                for a in self.aggregate_columns
            )
            lines.append(f"- Aggregates: {aggs}")
        if self.joins:
            jns = "; ".join(
                f"{j['left']} = {j['right']}" for j in self.joins
            )
            lines.append(f"- Joins: {jns}")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return not (
            self.tables
            or self.select_columns
            or self.filter_columns
            or self.aggregate_columns
        )


class SchemaAligner:
    def __init__(self, chat_model: BaseChatModel) -> None:
        self.chat_model = chat_model

    async def align(
        self, question: str, relevant_tables: list[dict], evidence: str = ""
    ) -> Alignment | None:
        """Run alignment with one validation retry. Returns None if the
        model can't produce a valid alignment — caller should proceed
        without the alignment block."""
        if not relevant_tables:
            return None

        schema_text = self._render_schema(relevant_tables)
        valid_cols = self._valid_columns(relevant_tables)

        user_msg = self._build_user_message(question, schema_text, evidence)
        raw = await self._call(user_msg)
        alignment, errors = self._parse_and_validate(raw, valid_cols)
        if alignment is not None:
            return alignment

        if errors:
            # One repair retry: inject validation errors and ask the model to fix.
            logger.info(
                f"[SchemaAligner] First alignment had validation errors; retrying"
            )
            retry_msg = (
                user_msg
                + "\n\nYour previous alignment had these errors:\n- "
                + "\n- ".join(errors[:8])
                + "\n\nReturn corrected JSON using only the schema columns above."
            )
            raw2 = await self._call(retry_msg)
            alignment2, _ = self._parse_and_validate(raw2, valid_cols)
            return alignment2
        return None

    async def _call(self, user_msg: str) -> str:
        try:
            resp = await self.chat_model.ainvoke(
                [SystemMessage(content=_ALIGNER_SYSTEM),
                 HumanMessage(content=user_msg)],
                temperature=0.0,
            )
            return resp.content if isinstance(resp.content, str) else str(resp.content)
        except Exception as e:
            logger.warning(f"[SchemaAligner] LLM call failed: {e}")
            return ""

    @staticmethod
    def _render_schema(relevant_tables: list[dict]) -> str:
        parts: list[str] = []
        for t in relevant_tables:
            name = t.get("table") or t.get("text") or "?"
            full = (t.get("full_desc") or "").split("|", 1)[0]
            parts.append(f"Table {name}:\n  {full.strip()}")
        return "\n\n".join(parts)

    @staticmethod
    def _build_user_message(question: str, schema: str, evidence: str) -> str:
        parts = [f"Schema:\n{schema}", "", f"Question: {question}"]
        if evidence:
            parts.append(f"Hint: {evidence}")
        return "\n".join(parts)

    @staticmethod
    def _valid_columns(relevant_tables: list[dict]) -> dict[str, set[str]]:
        """`{table_name_lower: {column_name_lower, ...}}`."""
        out: dict[str, set[str]] = {}
        for t in relevant_tables:
            name = (t.get("table") or t.get("text") or "").lower()
            cols_block = (t.get("desc_cols") or t.get("full_desc") or "").split("|", 1)[0]
            cols: set[str] = set()
            for part in cols_block.split(","):
                part = part.strip()
                paren = part.find(" (")
                colname = part[:paren].strip() if paren > 0 else part.split()[0] if part else ""
                if colname:
                    cols.add(colname.lower())
            out[name] = cols
        return out

    @staticmethod
    def _parse_and_validate(
        raw: str, valid_cols: dict[str, set[str]]
    ) -> tuple[Alignment | None, list[str]]:
        if not raw:
            return None, ["empty model response"]
        # Find the JSON object.
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None, ["no JSON object in response"]
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            return None, [f"JSON parse error: {e}"]

        a = Alignment(
            tables=data.get("tables", []) or [],
            select_columns=data.get("select_columns", []) or [],
            filter_columns=data.get("filter_columns", []) or [],
            aggregate_columns=data.get("aggregate_columns", []) or [],
            joins=data.get("joins", []) or [],
        )

        # Validation: every (table, column) must exist in the schema.
        errors: list[str] = []
        for col_set, label in (
            (a.select_columns, "select"),
            (a.filter_columns, "filter"),
            (a.aggregate_columns, "aggregate"),
        ):
            for entry in col_set:
                tbl = (entry.get("table") or "").lower()
                col = (entry.get("column") or "").lower()
                if tbl not in valid_cols:
                    errors.append(
                        f"{label}: table `{entry.get('table')}` is not in the schema"
                    )
                elif col not in valid_cols[tbl]:
                    errors.append(
                        f"{label}: column `{entry.get('column')}` is not on "
                        f"table `{entry.get('table')}`"
                    )

        if errors:
            return None, errors
        if a.is_empty():
            return None, ["empty alignment"]
        return a, []


__all__ = ["SchemaAligner", "Alignment"]
