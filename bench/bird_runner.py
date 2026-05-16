"""BIRD Mini-Dev runner with stratified sampling and cost tracking.

Run after `bench/bird_loader.py` has populated the BIRD databases and
registered the per-DB Text2SQL connections.

Usage::

    BENCH_MODELS=gpt-4o-mini uv run python -m bench.bird_runner --tier smoke
    BENCH_MODELS=gemini-2.5-pro uv run python -m bench.bird_runner --tier smoke --max-queries 5

Tiers (negotiated in pending_bird_bench.md):
  - smoke    :  30 queries, 10/15/5 simple/moderate/challenging, ≤6 DBs,  5/DB cap
  - standard :  80 queries, 30/30/20,                            ≤7 DBs, 12/DB cap
  - deep     : 200 queries, 60/100/40,                          all 11 DBs, 25/DB cap

Output: ./bench/results/bird_<tier>_<run-id>/{report.md,raw.json}.

Grading uses BIRD's Execution Accuracy: generated SQL and reference SQL
are re-executed on the same database; result sets are compared as
multisets (with order preserved when the reference SQL contains an
``ORDER BY``).

Token cost tracking: a langchain callback captures `usage_metadata` from
every LLM response. Costs are computed from the static price table
below; if a model isn't priced, only token counts are reported.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text as sqltext
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env", override=True)

from bench.bird_loader import (  # noqa: E402
    BIRD_PG_DATABASE,
    BIRD_QUESTIONS_JSON,
    HOST_BIND_ADDRESS,
    HOST_PORT,
    HOST_USER,
    HOST_PASSWORD,
    bird_connection_name,
)
from bench.run_bench import MODELS, ModelConfig  # noqa: E402

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from src.agents.services import MessageService  # noqa: E402
from src.agents.tools.init_tools import set_evidence  # noqa: E402
from src.common.credentials import CredentialStorage  # noqa: E402
from src.common.dto import Message  # noqa: E402
from src.common.metadata_db import MetadataDB  # noqa: E402
from src.common.settings import Settings  # noqa: E402
from src.services.embedding_service import EmbeddingService  # noqa: E402
from src.services.scanner_service import ScannerService  # noqa: E402

# USD per 1M tokens (input, output) — keep in sync with provider
# pricing pages. Gemini 3.x figures verified 2026-05-10 from
# ai.google.dev/gemini-api/docs/pricing. All values use the standard
# tier with ≤200K input context (our prompts never approach that).
PRICING: dict[str, tuple[float, float]] = {
    "gpt-3.5-turbo":         (0.50,  1.50),
    "gpt-4o-mini":           (0.15,  0.60),
    "gpt-4o":                (2.50, 10.00),
    "claude-sonnet-4-5":     (3.00, 15.00),
    "gemini-2.5-pro":        (1.25,  5.00),
    "gemini-2.5-flash":      (0.075, 0.30),
    "gemini-3.1-pro-preview":(2.00, 12.00),
    "gemini-3-flash-preview":(0.50,  3.00),
    "gemini-3.1-flash-lite": (0.25,  1.50),
}


@dataclass
class TierConfig:
    name: str
    total: int
    simple: int
    moderate: int
    challenging: int
    max_dbs: int
    per_db_cap: int


TIERS: dict[str, TierConfig] = {
    "smoke":    TierConfig("smoke",    30, 10, 15,  5,  6,  5),
    # mid mirrors the natural Mini-Dev 30/50/20 difficulty split — sample
    # size for cost-efficient attribution experiments.
    "mid":      TierConfig("mid",     100, 30, 50, 20, 11, 10),
    "standard": TierConfig("standard", 80, 30, 30, 20,  7, 12),
    "deep":     TierConfig("deep",    200, 60, 100, 40, 11, 25),
}


@dataclass
class BirdQuestion:
    question_id: int
    db_id: str
    question: str
    evidence: str
    SQL: str
    difficulty: str


@dataclass
class BirdResult:
    question_id: int
    db_id: str
    difficulty: str
    model: str
    # BIRD-official EX (1 if set(predicted_rows) == set(reference_rows)
    # exactly, else 0). This is the leaderboard metric.
    ex: int = 0
    # BIRD-official Soft F1 in [0, 1]. Precision/recall over per-row
    # value matches; partial credit when columns/rows partially overlap.
    soft_f1: float = 0.0
    # Convenience flag mirroring ex == 1, kept for the legacy report
    # printers.
    passed: bool = False
    reason: str = ""
    elapsed_s: float = 0.0
    generated_sql: str | None = None
    reference_sql: str | None = None
    # Full row dumps for forensics — every row, no truncation.
    # raw.json grows linearly with result-set sizes but at ~hundreds of
    # bytes per row × low-thousands of rows total it stays under 10 MB.
    generated_rows: list[list[Any]] = field(default_factory=list)
    expected_rows: list[list[Any]] = field(default_factory=list)
    generated_row_count: int = 0
    expected_row_count: int = 0
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    question: str = ""
    evidence: str = ""


class TokenCounter(BaseCallbackHandler):
    """Aggregates LLM input/output token counts across every call made
    through a chat model. Reset between questions to attribute usage
    accurately."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0

    def reset(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0

    def on_llm_end(self, response, **kwargs) -> None:
        # Try the usage_metadata path first (langchain >=0.3),
        # fall back to llm_output structures from older versions.
        try:
            for gen_list in getattr(response, "generations", []):
                for gen in gen_list:
                    msg = getattr(gen, "message", None)
                    usage = getattr(msg, "usage_metadata", None) if msg else None
                    if usage:
                        self.input_tokens += int(usage.get("input_tokens", 0))
                        self.output_tokens += int(usage.get("output_tokens", 0))
                        return
            llm_output = getattr(response, "llm_output", None) or {}
            tu = (llm_output.get("token_usage") or {}) if llm_output else {}
            self.input_tokens += int(tu.get("prompt_tokens", 0))
            self.output_tokens += int(tu.get("completion_tokens", 0))
        except Exception:
            # Better to under-count than crash the bench.
            pass


# ---- Sampling -------------------------------------------------------


def load_questions() -> list[BirdQuestion]:
    raw = json.loads(BIRD_QUESTIONS_JSON.read_text())
    return [BirdQuestion(**q) for q in raw]


def stratified_sample(
    questions: list[BirdQuestion],
    tier: TierConfig,
    seed: int = 42,
) -> list[BirdQuestion]:
    """Take a stratified sample. We:

    1. Pick the top `tier.max_dbs` BIRD logical DBs by question count
       (the dump combines all of them into one Postgres DB, but the
       db_id metadata still tells us which question targets which
       schema subset — useful for breakdown reporting).
    2. For each (difficulty, db_id) bucket, take up to `per_db_cap // 3`
       to keep DBs balanced across difficulties.
    3. Top up each difficulty bucket from any remaining DBs until the
       target count is hit.
    """
    rng = random.Random(seed)
    pool = list(questions)
    by_db = Counter(q.db_id for q in pool)
    chosen_dbs = {db for db, _ in by_db.most_common(tier.max_dbs)}
    pool = [q for q in pool if q.db_id in chosen_dbs]

    by_diff: dict[str, list[BirdQuestion]] = defaultdict(list)
    for q in pool:
        by_diff[q.difficulty].append(q)
    for qs in by_diff.values():
        rng.shuffle(qs)

    targets = {
        "simple": tier.simple,
        "moderate": tier.moderate,
        "challenging": tier.challenging,
    }

    sampled: list[BirdQuestion] = []
    per_db_per_diff = max(1, tier.per_db_cap // 3)

    for difficulty, target in targets.items():
        bucket = by_diff[difficulty]
        per_db = defaultdict(int)
        first_pass: list[BirdQuestion] = []
        leftover: list[BirdQuestion] = []
        for q in bucket:
            if per_db[q.db_id] < per_db_per_diff and len(first_pass) < target:
                first_pass.append(q)
                per_db[q.db_id] += 1
            else:
                leftover.append(q)
        # Top up if first pass underfilled.
        need = target - len(first_pass)
        first_pass.extend(leftover[:need])
        sampled.extend(first_pass[:target])

    return sampled


# ---- Grading --------------------------------------------------------
#
# Mirrors BIRD's official Mini-Dev evaluator
# (github.com/bird-bench/mini_dev/blob/main/evaluation/{evaluation_ex.py,
# evaluation_f1.py}). Two metrics:
#
#   EX (Execution Accuracy) — 1 if set(predicted) == set(ground_truth)
#       as raw tuples returned by the DB driver, else 0. NO precision
#       tolerance, NO type coercion. This is the leaderboard metric.
#
#   Soft F1 — per-row value-overlap F1 in [0, 1]. Partial credit when
#       rows have overlapping values but different column counts/order.
#       Useful diagnostic for "almost right" answers.
#
# Both queries are executed against the SAME DB connection so the DB
# driver returns consistent Python types for both sides — that's how
# BIRD avoids the Decimal/float headache without coercion.


async def _execute(engine, sql: str) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        result = await conn.execute(sqltext(sql))
        return [tuple(r) for r in result.fetchall()]


def _calculate_ex(predicted: list[tuple], ground_truth: list[tuple]) -> int:
    """BIRD's exact EX: strict set-of-tuples comparison."""
    return 1 if set(predicted) == set(ground_truth) else 0


def _calculate_row_match(
    predicted_row: tuple, ground_truth_row: tuple
) -> tuple[float, float, float]:
    """BIRD's row-level value match (evaluation_f1.calculate_row_match).
    Returns (match_pct, pred_only_pct, truth_only_pct)."""
    total_columns = len(ground_truth_row) or 1
    matches = 0
    element_in_pred_only = 0
    element_in_truth_only = 0
    for pred_val in predicted_row:
        if pred_val in ground_truth_row:
            matches += 1
        else:
            element_in_pred_only += 1
    for truth_val in ground_truth_row:
        if truth_val not in predicted_row:
            element_in_truth_only += 1
    return (
        matches / total_columns,
        element_in_pred_only / total_columns,
        element_in_truth_only / total_columns,
    )


def _calculate_soft_f1(
    predicted: list[tuple], ground_truth: list[tuple]
) -> float:
    """BIRD's Soft F1 (evaluation_f1.calculate_f1_score). Drop dupes,
    compare row-by-row at the same index, accumulate precision/recall."""
    if not predicted and not ground_truth:
        return 1.0
    # Drop duplicates while preserving order (BIRD uses dict.fromkeys).
    pred = list(dict.fromkeys(predicted))
    gt = list(dict.fromkeys(ground_truth))

    match_scores: list[float] = []
    pred_only_scores: list[float] = []
    truth_only_scores: list[float] = []

    for i, gt_row in enumerate(gt):
        if i >= len(pred):
            match_scores.append(0)
            truth_only_scores.append(1)
            continue
        m, p_only, t_only = _calculate_row_match(pred[i], gt_row)
        match_scores.append(m)
        pred_only_scores.append(p_only)
        truth_only_scores.append(t_only)

    for _ in range(len(pred) - len(gt)):
        match_scores.append(0)
        pred_only_scores.append(1)
        truth_only_scores.append(0)

    tp = sum(match_scores)
    fp = sum(pred_only_scores)
    fn = sum(truth_only_scores)
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    return (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )


def _row_to_jsonable(row: tuple) -> list[Any]:
    """Convert a DB row to JSON-serializable values for the report
    (Decimal → str, datetime → iso, bytes → utf-8 with replace)."""
    from decimal import Decimal
    from datetime import date, datetime as _dt, time as _time
    out: list[Any] = []
    for v in row:
        if v is None or isinstance(v, (str, int, float, bool)):
            out.append(v)
        elif isinstance(v, Decimal):
            out.append(str(v))
        elif isinstance(v, (date, _dt, _time)):
            out.append(v.isoformat())
        elif isinstance(v, bytes):
            out.append(v.decode("utf-8", errors="replace"))
        else:
            out.append(str(v))
    return out


async def grade_bird(
    question: BirdQuestion, generated_sql: str | None, db_engine
) -> tuple[int, float, str, list[tuple], list[tuple]]:
    """Run BIRD-official EX + Soft F1 grading. Returns
    (ex, soft_f1, reason, generated_rows, expected_rows). Both row lists
    are returned so callers can serialize them for the audit trail."""
    if not generated_sql:
        return 0, 0.0, "no SQL generated", [], []

    try:
        actual = await _execute(db_engine, generated_sql)
    except Exception as e:
        return 0, 0.0, f"generated SQL did not execute: {e}", [], []

    try:
        expected = await _execute(db_engine, question.SQL)
    except Exception as e:
        return 0, 0.0, f"reference SQL failed (BIRD-side bug): {e}", [], []

    ex = _calculate_ex(actual, expected)
    soft_f1 = _calculate_soft_f1(actual, expected)
    if ex == 1:
        reason = f"EX=1, F1=1.00 ({len(expected)} rows)"
    else:
        reason = (
            f"EX=0, F1={soft_f1:.2f} | "
            f"actual={len(actual)} / expected={len(expected)} rows"
        )
    return ex, soft_f1, reason, actual, expected


# ---- Runner ---------------------------------------------------------


def _make_settings(model: ModelConfig) -> Settings:
    overrides: dict[str, Any] = {
        "llm_provider": model.provider,
        "model_id": model.model_id,
    }
    if model.provider == "openai":
        overrides["openai_api_key"] = os.environ["OPENAI_API_KEY"]
    elif model.provider == "anthropic":
        overrides["anthropic_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    elif model.provider == "google":
        overrides["google_api_key"] = os.environ["GOOGLE_API_KEY"]

    # gpt-3.5-turbo caps completion tokens at 4096; the production
    # default (16000) trips OpenAI's validation. Clamp per-model.
    if model.id == "gpt-3.5-turbo":
        overrides["max_tokens_agent"] = 4096
        overrides["max_tokens_client"] = 4096
    return Settings(**overrides)


def _bird_engine():
    url = URL.create(
        "postgresql+asyncpg",
        username=HOST_USER,
        password=HOST_PASSWORD,
        host=HOST_BIND_ADDRESS,
        port=HOST_PORT,
        database=BIRD_PG_DATABASE,
    )
    return create_async_engine(url, pool_pre_ping=True)


def _select_models() -> list[ModelConfig]:
    requested = os.environ.get("BENCH_MODELS")
    if not requested:
        return [m for m in MODELS if all(os.environ.get(k) for k in m.env_keys)]
    wanted = {x.strip() for x in requested.split(",") if x.strip()}
    return [m for m in MODELS if m.id in wanted]


def _bird_connection_map(storage: CredentialStorage) -> dict[str, str]:
    """Return `{db_id: connection_id}` for every per-db_id BIRD connection."""
    out: dict[str, str] = {}
    for c in storage.list_connections():
        if c.name.startswith("bird-") and c.name != "bird-dev":
            out[c.name.removeprefix("bird-")] = c.id
    return out


def _build_message_service(
    settings: Settings, metadata_engine
) -> tuple[MessageService, ScannerService, EmbeddingService, TokenCounter]:
    es = EmbeddingService(metadata_engine=metadata_engine)
    scanner = ScannerService(settings=settings, embedding_service=es)
    counter = TokenCounter()
    ms = MessageService(
        settings,
        scanner_service=scanner,
        metadata_engine=metadata_engine,
        embedding_service=es,
    )
    # Patch the in-place LLM constructor to attach the counter callback.
    # The existing factory builds a fresh client in MessageService._build_agent
    # — we intercept by overriding `create_llm_from_settings` for this scope.
    import src.agents.services as services_mod
    from src.llm.utils import create_llm_from_settings as _orig_create

    # Per-model completion-token caps. Some agent code paths pass
    # max_tokens=10000 directly to ainvoke, which overrides the
    # constructor setting and crashes on models with smaller caps.
    # Clamp the kwarg at invoke time as a bench-only patch so we don't
    # have to ripple max_tokens defaults through prod code.
    MODEL_OUTPUT_CAPS: dict[str, int] = {
        "gpt-3.5-turbo": 4096,
    }

    def _wrapped_create(*args, **kwargs):
        llm = _orig_create(*args, **kwargs)
        try:
            llm.callbacks = (llm.callbacks or []) + [counter]
        except Exception:
            pass

        cap = MODEL_OUTPUT_CAPS.get(settings.model_id or "")
        if cap is not None:
            # ChatOpenAI is a pydantic model and blocks instance attr
            # assignment, so patch the class-level ainvoke (one-time per
            # type). Idempotent: a second wrap will re-clamp the same way.
            cls = type(llm)
            if not getattr(cls, "_bench_max_tokens_patched", False):
                orig_ainvoke = cls.ainvoke

                async def clamped_ainvoke(self, *a, _cap=cap, **kw):
                    if "max_tokens" in kw and kw["max_tokens"] is not None:
                        kw["max_tokens"] = min(int(kw["max_tokens"]), _cap)
                    return await orig_ainvoke(self, *a, **kw)

                cls.ainvoke = clamped_ainvoke
                cls._bench_max_tokens_patched = True
        return llm

    services_mod.create_llm_from_settings = _wrapped_create
    return ms, scanner, es, counter


# ---- Attribution experiment patches ---------------------------------
#
# These rewrite pieces of the pipeline in-place to test specific
# hypotheses about why the pipeline regresses vs the bare baseline.
# Each is gated on an env var so the production pipeline is unaffected
# unless explicitly opted-in for a bench run.


_DEV_TABLES_CACHE: dict[str, dict] | None = None


def _load_dev_tables_per_db() -> dict[str, dict]:
    """Return `{db_id: dev_tables_entry}` from BIRD's dev_tables.json."""
    global _DEV_TABLES_CACHE
    if _DEV_TABLES_CACHE is None:
        from bench.bird_loader import BIRD_UNZIPPED_DIR
        path = BIRD_UNZIPPED_DIR / "MINIDEV" / "dev_tables.json"
        raw = json.loads(path.read_text())
        _DEV_TABLES_CACHE = {e["db_id"]: e for e in raw}
    return _DEV_TABLES_CACHE


def _canonical_schema_for(db_id: str) -> str:
    """Render BIRD's canonical schema for one db_id — same format as
    bird_baseline.py uses. Tables + typed columns + foreign keys."""
    entry = _load_dev_tables_per_db()[db_id]
    tables = entry["table_names_original"]
    cols = entry["column_names_original"]
    types = entry["column_types"]
    fks = entry.get("foreign_keys", []) or []

    by_table: dict[int, list[tuple[str, str]]] = {i: [] for i in range(len(tables))}
    for i, (tbl_idx, col_name) in enumerate(cols):
        if tbl_idx == -1:
            continue
        by_table[tbl_idx].append((col_name, types[i]))

    parts: list[str] = []
    for idx, tname in enumerate(tables):
        cs = ", ".join(f"{c} ({t})" for c, t in by_table.get(idx, []))
        parts.append(f"Table {tname}:\n  {cs}")
    if fks:
        fk_lines = []
        for left_col_idx, right_col_idx in fks:
            l_tbl, l_col = cols[left_col_idx]
            r_tbl, r_col = cols[right_col_idx]
            if l_tbl == -1 or r_tbl == -1:
                continue
            fk_lines.append(f"  {tables[l_tbl]}.{l_col} -> {tables[r_tbl]}.{r_col}")
        if fk_lines:
            parts.append("Foreign keys:\n" + "\n".join(fk_lines))
    return "\n\n".join(parts)


def _apply_attribution_patches() -> dict[str, bool]:
    """Apply opt-in monkey-patches based on env vars. Idempotent.
    Returns the active patch flags so they can be logged in the report."""
    flags = {
        "simple_schema": bool(os.environ.get("BENCH_SIMPLE_SCHEMA")),
        "simple_prompt": bool(os.environ.get("BENCH_SIMPLE_PROMPT")),
        "full_schema":   bool(os.environ.get("BENCH_FULL_SCHEMA")),
    }
    if not any(flags.values()):
        return flags

    import src.agents.tools.sql_creator as sc_mod
    from src.agents.tools.sql_creator import SQLCreator

    # ---- (A) canonical schema rendering ----
    # Replace SQLCreator._render_tables with a renderer that uses our
    # vector-retrieved tables but in BIRD's canonical "Table foo:\n
    # cols\nForeign keys:\n …" layout (no value hints, no junction
    # commentary). Tests whether the renderer's noise is the cause.
    if flags["simple_schema"] and not getattr(SQLCreator, "_bench_simple_schema", False):
        def _render_simple(list_tables, desc_data):
            parts = []
            for t in list_tables:
                full = t.get("full_desc") or ""
                # Pull out the column list from full_desc — strip value-hints
                # and "Table:"/"Description:" prefixes; keep "Columns: …" line.
                lines = full.split("\n")
                name = t.get("table") or t.get("text") or "?"
                cols_line = ""
                for ln in lines:
                    if ln.startswith("Columns"):
                        # Drop the "(use exact names): " prefix.
                        cols_line = ln.split(":", 1)[-1].strip()
                        cols_line = cols_line.split("|", 1)[0].strip()
                        break
                if not cols_line:
                    cols_line = t.get("desc_cols", "").split("|", 1)[0].strip()
                parts.append(f"Table {name}:\n  {cols_line}")
                fk = ""
                for ln in lines:
                    if ln.startswith("Foreign Keys"):
                        fk = ln.split(":", 1)[-1].strip()
                        break
                if fk:
                    parts.append(f"Foreign keys for {name}:\n  {fk}")
            return "\n\n".join(parts) + "\n"
        SQLCreator._render_tables = staticmethod(_render_simple)
        SQLCreator._bench_simple_schema = True

    # ---- (C) simple BIRD-style system prompt ----
    if flags["simple_prompt"] and not getattr(SQLCreator, "_bench_simple_prompt", False):
        BIRD_SIMPLE_PROMPT = (
            "You are an expert PostgreSQL query writer. Given a schema "
            "and a natural-language question (with optional evidence), "
            "write exactly one PostgreSQL SELECT statement that answers "
            "the question. Use only the columns and tables shown. "
            "Output strict JSON: {\"sql_query\": \"<your SELECT>\"}. "
            "Return nothing else."
        )
        sc_mod.SYSTEM_PROMPT = BIRD_SIMPLE_PROMPT
        SQLCreator._bench_simple_prompt = True

    # ---- (B4) full db_id schema, bypass retrieval+filter ----
    # Replace VectorStore.search with a function that returns synthetic
    # table dicts built from dev_tables.json for the active connection's
    # db_id. Same fields the SQL creator expects (`full_desc, desc_cols,
    # comment, table, distance`) so downstream code is happy.
    if flags["full_schema"] and not getattr(SQLCreator, "_bench_full_schema", False):
        from src.agents.tools import required_tables_searcher as vs_mod
        from bench.bird_loader import bird_connection_name, CONNECTION_ID_PREFIX
        from src.common.credentials import CredentialStorage

        _orig_search = vs_mod.VectorStore.search

        async def full_schema_search(self, query_text, **kw):
            # Find the BIRD db_id this connection is bound to via the
            # active connection's stored name.
            settings = Settings()
            storage = CredentialStorage(
                settings.credential_storage_path,
                settings.credential_encryption_key,
            )
            try:
                # The active connection_id is what VectorStore is scoped to.
                conn = next(
                    c for c in storage.list_connections()
                    if c.id == self.connection_id
                )
            except StopIteration:
                return await _orig_search(self, query_text, **kw)
            if not conn.name.startswith(CONNECTION_ID_PREFIX):
                return await _orig_search(self, query_text, **kw)
            db_id = conn.name.removeprefix(CONNECTION_ID_PREFIX)
            entry = _load_dev_tables_per_db().get(db_id)
            if entry is None:
                return await _orig_search(self, query_text, **kw)

            tables = entry["table_names_original"]
            cols = entry["column_names_original"]
            types = entry["column_types"]
            fks = entry.get("foreign_keys", []) or []

            by_table: dict[int, list[tuple[str, str]]] = {
                i: [] for i in range(len(tables))
            }
            for i, (tbl_idx, col_name) in enumerate(cols):
                if tbl_idx == -1:
                    continue
                by_table[tbl_idx].append((col_name, types[i]))

            # Per-table FK strings.
            fks_by_table: dict[int, list[str]] = {i: [] for i in range(len(tables))}
            for left_idx, right_idx in fks:
                lt, lc = cols[left_idx]
                rt, rc = cols[right_idx]
                if lt == -1 or rt == -1:
                    continue
                fks_by_table[lt].append(f"{lc} -> {tables[rt]}.{rc}")

            out: list[dict] = []
            for i, tname in enumerate(tables):
                cs = ", ".join(f"{c} ({t})" for c, t in by_table[i])
                fk_str = "; ".join(fks_by_table[i])
                full_desc = (
                    f"Table: {tname}\n"
                    f"Columns (use exact names): {cs}\n"
                    + (f"Foreign Keys: {fk_str}\n" if fk_str else "")
                )
                out.append({
                    "id": tname,
                    "table": tname,
                    "distance": 0.0,
                    "comment": "",
                    "full_desc": full_desc,
                    "desc_cols": cs,
                })
            return out

        vs_mod.VectorStore.search = full_schema_search
        SQLCreator._bench_full_schema = True

    return flags


async def run_one_question(
    question: BirdQuestion,
    model: ModelConfig,
    message_service: MessageService,
    counter: TokenCounter,
    db_engine,
) -> BirdResult:
    # Evidence is threaded via a ContextVar (init_tools.set_evidence)
    # so the SQL creator can present it as a labelled section instead
    # of having it muddled into the question text.
    msg = Message(
        role="user",
        content=question.question,
        type="plain",
    )
    set_evidence(question.evidence)

    counter.reset()
    started = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            message_service.process_messages([msg]), timeout=180
        )
    except asyncio.TimeoutError:
        return BirdResult(
            question_id=question.question_id, db_id=question.db_id,
            difficulty=question.difficulty, model=model.id,
            ex=0, soft_f1=0.0, passed=False, reason="timeout (>180s)",
            elapsed_s=time.perf_counter() - started, error="timeout",
            reference_sql=question.SQL,
            question=question.question, evidence=question.evidence,
        )
    except Exception as e:
        return BirdResult(
            question_id=question.question_id, db_id=question.db_id,
            difficulty=question.difficulty, model=model.id,
            ex=0, soft_f1=0.0, passed=False,
            reason=f"pipeline raised {type(e).__name__}",
            elapsed_s=time.perf_counter() - started,
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1000]}",
            reference_sql=question.SQL,
            question=question.question, evidence=question.evidence,
        )

    elapsed = time.perf_counter() - started
    sql = response.sql_query
    ex, soft_f1, reason, gen_rows, exp_rows = await grade_bird(
        question, sql, db_engine
    )

    in_price, out_price = PRICING.get(model.id, (0.0, 0.0))
    cost = (
        counter.input_tokens / 1e6 * in_price
        + counter.output_tokens / 1e6 * out_price
    )

    return BirdResult(
        question_id=question.question_id,
        db_id=question.db_id,
        difficulty=question.difficulty,
        model=model.id,
        ex=ex,
        soft_f1=soft_f1,
        passed=(ex == 1),
        reason=reason,
        elapsed_s=elapsed,
        generated_sql=sql,
        reference_sql=question.SQL,
        generated_rows=[_row_to_jsonable(r) for r in gen_rows],
        expected_rows=[_row_to_jsonable(r) for r in exp_rows],
        generated_row_count=len(gen_rows),
        expected_row_count=len(exp_rows),
        input_tokens=counter.input_tokens,
        output_tokens=counter.output_tokens,
        cost_usd=cost,
        question=question.question,
        evidence=question.evidence,
    )


async def run_model(
    model: ModelConfig,
    questions: list[BirdQuestion],
    storage: CredentialStorage,
) -> list[BirdResult]:
    print(f"\n=== {model.id} ({model.provider}/{model.model_id}) ===")
    settings = _make_settings(model)

    conn_map = _bird_connection_map(storage)
    if not conn_map:
        return [
            BirdResult(
                q.question_id, q.db_id, q.difficulty, model.id,
                False, "no per-db_id BIRD connections registered",
            )
            for q in questions
        ]

    # Cluster by db_id so we minimize active-connection swaps (each swap
    # forces MessageService to rebuild engine + vector_store).
    by_db: dict[str, list[BirdQuestion]] = defaultdict(list)
    for q in questions:
        by_db[q.db_id].append(q)

    md = MetadataDB(settings)
    await md.bootstrap()
    ms, scanner, es, counter = _build_message_service(settings, md.engine)
    db_engine = _bird_engine()

    results: list[BirdResult] = []
    try:
        for db_id, qs in by_db.items():
            conn_id = conn_map.get(db_id)
            if conn_id is None:
                for q in qs:
                    results.append(BirdResult(
                        q.question_id, q.db_id, q.difficulty, model.id,
                        False, f"no connection registered for db_id {db_id!r}",
                    ))
                continue
            storage.set_active_connection(conn_id)
            # Force the cached agent to rebuild against the new connection
            # on the next process_messages call.
            await ms.close()

            for q in qs:
                r = await run_one_question(q, model, ms, counter, db_engine)
                status = "PASS" if r.ex == 1 else "FAIL"
                print(
                    f"  [{status}] q{r.question_id:5d} {r.difficulty[:4]:4s} "
                    f"{r.db_id[:18]:18s} EX={r.ex} F1={r.soft_f1:.2f} "
                    f"{r.elapsed_s:5.1f}s "
                    f"in={r.input_tokens:5d} out={r.output_tokens:4d} "
                    f"${r.cost_usd:.4f}  {r.reason[:40]}"
                )
                results.append(r)
    finally:
        await db_engine.dispose()
        await ms.close()
        await scanner.close()
        await md.close()

    return results


def _aggregate(rs: list[BirdResult]) -> dict[str, Any]:
    """BIRD-style aggregate metrics per result list. Mean EX × 100, mean
    Soft F1 × 100, broken down by difficulty + total counts."""
    totals = {"simple": [0, 0.0, 0], "moderate": [0, 0.0, 0],
              "challenging": [0, 0.0, 0], "total": [0, 0.0, 0]}
    for r in rs:
        for bucket in (r.difficulty, "total"):
            totals[bucket][0] += r.ex
            totals[bucket][1] += r.soft_f1
            totals[bucket][2] += 1
    out: dict[str, Any] = {}
    for bucket, (ex_sum, f1_sum, count) in totals.items():
        if count == 0:
            out[bucket] = {"ex": 0.0, "soft_f1": 0.0, "count": 0}
        else:
            out[bucket] = {
                "ex": ex_sum / count * 100,
                "soft_f1": f1_sum / count * 100,
                "count": count,
            }
    return out


def write_report(
    run_dir: Path,
    model_results: dict[str, list[BirdResult]],
    config: dict[str, Any],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    # Full per-question dump for forensics — generated/expected rows,
    # both SQLs, all metrics. This is the source of truth; report.md is
    # a digest.
    raw = {m: [asdict(r) for r in rs] for m, rs in model_results.items()}
    (run_dir / "raw.json").write_text(json.dumps(raw, indent=2, default=str))

    # Compact per-model metric summaries (BIRD-style printout).
    summary: dict[str, Any] = {"config": config, "models": {}}
    for model_id, rs in model_results.items():
        agg = _aggregate(rs)
        in_tok = sum(r.input_tokens for r in rs)
        out_tok = sum(r.output_tokens for r in rs)
        cost = sum(r.cost_usd for r in rs)
        summary["models"][model_id] = {
            "metrics": agg,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": cost,
            "avg_input_tokens_per_q": in_tok / len(rs) if rs else 0,
            "avg_output_tokens_per_q": out_tok / len(rs) if rs else 0,
            "avg_cost_per_q": cost / len(rs) if rs else 0,
            "avg_elapsed_s": (sum(r.elapsed_s for r in rs) / len(rs)) if rs else 0,
        }
    (run_dir / "metrics.json").write_text(json.dumps(summary, indent=2, default=str))

    lines: list[str] = []
    lines.append(
        f"# BIRD Mini-Dev — {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    )
    lines.append("")
    lines.append("## Configuration")
    for k, v in config.items():
        lines.append(f"- **{k}**: {v}")

    lines.append("\n## EX (Execution Accuracy) — BIRD-official metric\n")
    lines.append(
        "| Model | Simple | Moderate | Challenging | **Total** |"
    )
    lines.append("|" + "---|" * 5)
    for model_id, rs in model_results.items():
        agg = _aggregate(rs)
        cells = [model_id]
        for bucket in ("simple", "moderate", "challenging", "total"):
            d = agg[bucket]
            if d["count"] == 0:
                cells.append("—")
            else:
                cells.append(f"{d['ex']:.2f} ({d['count']})")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("\n## Soft F1 — BIRD-official partial-credit metric\n")
    lines.append(
        "| Model | Simple | Moderate | Challenging | **Total** |"
    )
    lines.append("|" + "---|" * 5)
    for model_id, rs in model_results.items():
        agg = _aggregate(rs)
        cells = [model_id]
        for bucket in ("simple", "moderate", "challenging", "total"):
            d = agg[bucket]
            if d["count"] == 0:
                cells.append("—")
            else:
                cells.append(f"{d['soft_f1']:.2f} ({d['count']})")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("\n## Cost & token usage\n")
    lines.append(
        "| Model | Tokens (in / out) | Avg per Q (in / out) | "
        "Avg latency | Total cost |"
    )
    lines.append("|" + "---|" * 5)
    for model_id, rs in model_results.items():
        m = summary["models"][model_id]
        lines.append(
            f"| {model_id} | {m['input_tokens']} / {m['output_tokens']} | "
            f"{m['avg_input_tokens_per_q']:.0f} / "
            f"{m['avg_output_tokens_per_q']:.0f} | "
            f"{m['avg_elapsed_s']:.1f}s | ${m['cost_usd']:.3f} |"
        )

    # Per-DB EX breakdown.
    lines.append("\n## EX by database\n")
    lines.append("| DB | " + " | ".join(model_results.keys()) + " |")
    lines.append("|" + "---|" * (len(model_results) + 1))
    all_dbs: set[str] = set()
    for rs in model_results.values():
        all_dbs.update(r.db_id for r in rs)
    for db_id in sorted(all_dbs):
        cells = [db_id]
        for model_id, rs in model_results.items():
            sub = [r for r in rs if r.db_id == db_id]
            if not sub:
                cells.append("—")
                continue
            ex = sum(r.ex for r in sub) / len(sub) * 100
            cells.append(f"{ex:.0f} ({sum(r.ex for r in sub)}/{len(sub)})")
        lines.append("| " + " | ".join(cells) + " |")

    # All failures (we keep them all, not just first 10 — full audit
    # trail since this is one-shot work).
    lines.append("\n## All failures (EX=0)\n")
    for model_id, rs in model_results.items():
        fails = [r for r in rs if r.ex == 0]
        if not fails:
            lines.append(f"\n### {model_id}: clean — no failures.\n")
            continue
        lines.append(f"\n### {model_id} ({len(fails)} failures)\n")
        for r in fails:
            lines.append(
                f"- q{r.question_id} ({r.db_id}/{r.difficulty}) "
                f"F1={r.soft_f1:.2f} — {r.reason[:120]}"
            )
            lines.append(f"  - **Q**: {r.question[:200]}")
            if r.evidence:
                lines.append(f"  - **Hint**: {r.evidence[:200]}")
            if r.generated_sql:
                lines.append(
                    f"  - **Generated**: `{r.generated_sql.strip()[:300]}`"
                )
            if r.reference_sql:
                lines.append(
                    f"  - **Reference**: `{r.reference_sql.strip()[:300]}`"
                )
            if r.error:
                lines.append(f"  - **Error**: {r.error[:200]}")

    (run_dir / "report.md").write_text("\n".join(lines))
    print(f"\nReport: {run_dir / 'report.md'}")
    print(f"Metrics: {run_dir / 'metrics.json'}")
    print(f"Raw (full rows): {run_dir / 'raw.json'}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="BIRD Mini-Dev runner")
    parser.add_argument(
        "--tier", choices=list(TIERS), default="smoke",
        help="Sampling tier (smoke/standard/deep) — ignored when --all is set",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run every BIRD Mini-Dev question (500 total). "
             "Bypasses --tier and --max-queries.",
    )
    parser.add_argument(
        "--max-queries", type=int, default=None,
        help="Hard cap on total queries (overrides tier total)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Sampling seed for reproducibility",
    )
    parser.add_argument(
        "--subset", type=str, default=None,
        help="Run a curated subset. Currently supports 'problematic': "
             "every question where the prior pipeline run failed "
             "(ex==0). Reads question IDs from --subset-source raw.json "
             "(default: bench/results/bird_full_20260510_212541/raw.json).",
    )
    parser.add_argument(
        "--subset-source", type=str,
        default="bench/results/bird_full_20260510_212541/raw.json",
        help="Path to a prior raw.json used as the source of question IDs "
             "for --subset modes. Relative paths are resolved against the "
             "repo root.",
    )
    args = parser.parse_args()

    if not BIRD_QUESTIONS_JSON.exists():
        print(f"Questions file missing at {BIRD_QUESTIONS_JSON}.", file=sys.stderr)
        print("Run `uv run python -m bench.bird_loader` first.", file=sys.stderr)
        return 2

    settings = Settings()
    if not settings.credential_encryption_key:
        print("CREDENTIAL_ENCRYPTION_KEY missing; set it in .env", file=sys.stderr)
        return 2

    storage = CredentialStorage(
        settings.credential_storage_path,
        settings.credential_encryption_key,
    )
    if not _bird_connection_map(storage):
        print(
            "No per-db_id BIRD connections found. "
            "Run `uv run python -m bench.bird_loader` first.",
            file=sys.stderr,
        )
        return 2

    questions = load_questions()
    if args.subset:
        if args.subset != "problematic":
            print(
                f"Unknown subset: {args.subset!r}. Supported: 'problematic'.",
                file=sys.stderr,
            )
            return 2
        src = Path(args.subset_source)
        if not src.is_absolute():
            src = REPO_ROOT / src
        if not src.exists():
            print(f"--subset-source missing: {src}", file=sys.stderr)
            return 2
        raw = json.loads(src.read_text())
        # raw.json is keyed by model id; pick the first entry deterministically.
        model_keys = list(raw.keys())
        if not model_keys:
            print(f"--subset-source has no model entries: {src}", file=sys.stderr)
            return 2
        records = raw[model_keys[0]]
        failed_ids: set[int] = {
            r["question_id"] for r in records if r.get("ex") == 0
        }
        sampled = [q for q in questions if q.question_id in failed_ids]
        if not sampled:
            print(
                "No questions matched the problematic subset — source raw.json "
                "may correspond to a different question set.",
                file=sys.stderr,
            )
            return 2
        if args.max_queries is not None:
            sampled = sampled[: args.max_queries]
        tier = TierConfig(
            name=f"subset-{args.subset}",
            total=len(sampled),
            simple=sum(1 for q in sampled if q.difficulty == "simple"),
            moderate=sum(1 for q in sampled if q.difficulty == "moderate"),
            challenging=sum(1 for q in sampled if q.difficulty == "challenging"),
            max_dbs=11,
            per_db_cap=99,
        )
        print(f"Subset 'problematic' loaded from {src}: {len(sampled)} questions.")
    elif args.all:
        # No sampling — run every Mini-Dev question. Used for
        # leaderboard-comparable runs.
        sampled = list(questions)
        tier = TierConfig(
            name="full",
            total=len(sampled),
            simple=sum(1 for q in sampled if q.difficulty == "simple"),
            moderate=sum(1 for q in sampled if q.difficulty == "moderate"),
            challenging=sum(1 for q in sampled if q.difficulty == "challenging"),
            max_dbs=11,
            per_db_cap=99,
        )
    else:
        tier = TIERS[args.tier]
        sampled = stratified_sample(questions, tier, seed=args.seed)
        if args.max_queries is not None:
            sampled = sampled[: args.max_queries]

    diff_hist = Counter(q.difficulty for q in sampled)
    db_hist = Counter(q.db_id for q in sampled)
    print(
        f"Sampled {len(sampled)} questions: "
        f"difficulty {dict(diff_hist)} / "
        f"DBs {dict(db_hist)}"
    )

    models = _select_models()
    if not models:
        print("No runnable models. Set BENCH_MODELS or provider API keys.")
        return 1

    # Save the active connection so we can restore it after the run.
    prev_active = storage.get_active_connection()
    prev_active_id = prev_active.id if prev_active else None

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if args.subset:
        tier_label = f"subset-{args.subset}"
    elif args.all:
        tier_label = "full"
    else:
        tier_label = args.tier
    run_dir = REPO_ROOT / "bench" / "results" / f"bird_{tier_label}_{run_id}"

    # Apply attribution-experiment patches before any LLM run so the
    # whole sweep sees them. Logged into the run config for traceability.
    patch_flags = _apply_attribution_patches()

    config = {
        "run_id": run_id,
        "tier": args.tier,
        "tier_targets": asdict(tier),
        "max_queries": args.max_queries,
        "seed": args.seed,
        "models": [m.id for m in models],
        "model_provider_map": {m.id: f"{m.provider}/{m.model_id}" for m in models},
        "sampled_count": len(sampled),
        "difficulty_histogram": dict(Counter(q.difficulty for q in sampled)),
        "db_histogram": dict(Counter(q.db_id for q in sampled)),
        "question_ids": [q.question_id for q in sampled],
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "grader": "BIRD-official EX + Soft F1 "
                  "(github.com/bird-bench/mini_dev/evaluation)",
        "attribution_patches": patch_flags,
    }

    model_results: dict[str, list[BirdResult]] = {}
    try:
        for m in models:
            try:
                model_results[m.id] = await run_model(m, sampled, storage)
            except Exception as e:
                print(f"[fatal] {m.id}: {e}")
                traceback.print_exc()
                model_results[m.id] = []
    finally:
        if prev_active_id:
            try:
                storage.set_active_connection(prev_active_id)
            except Exception:
                pass

    config["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_report(run_dir, model_results, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
