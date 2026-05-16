"""Run NL→SQL benchmark across multiple LLM models.

Each model is exercised through the full Text2SQL pipeline (vector search →
table filter → SQL generation → execution → self-correction loop). The
agent's generated SQL is graded against a deterministic reference query
re-executed through the same connection.

Usage::

    uv run python -m bench.run_bench

Override which models to run by editing MODELS below or by setting
``BENCH_MODELS`` to a comma-separated list of ids that match a config in
MODELS (e.g. ``BENCH_MODELS=gpt-4o-mini,gemini-2.5-pro``).

Required environment per model:
- gpt-*  → OPENAI_API_KEY
- claude-* → ANTHROPIC_API_KEY
- gemini-* → GOOGLE_API_KEY

Output:
- ./bench/results/<run-id>/report.md   – human readable matrix
- ./bench/results/<run-id>/raw.json    – full per-case detail
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text as sqltext
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

# Make `src` importable when running from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load .env with override so .env values win over the OS-provided
# defaults (e.g. macOS sets USERNAME to the login name).
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from bench.queries import CASES, Case  # noqa: E402
from src.agents.services import MessageService  # noqa: E402
from src.common.dto import Message  # noqa: E402
from src.common.metadata_db import MetadataDB  # noqa: E402
from src.common.settings import Settings  # noqa: E402
from src.services.embedding_service import EmbeddingService  # noqa: E402
from src.services.scanner_service import ScannerService  # noqa: E402


@dataclass(frozen=True)
class ModelConfig:
    id: str  # short label
    provider: str
    model_id: str
    env_keys: tuple[str, ...] = ()


MODELS: list[ModelConfig] = [
    ModelConfig("gpt-3.5-turbo", "openai", "gpt-3.5-turbo", ("OPENAI_API_KEY",)),
    ModelConfig("gpt-4o-mini", "openai", "gpt-4o-mini", ("OPENAI_API_KEY",)),
    ModelConfig("gpt-4o", "openai", "gpt-4o", ("OPENAI_API_KEY",)),
    ModelConfig("claude-sonnet-4-5", "anthropic", "claude-sonnet-4-5", ("ANTHROPIC_API_KEY",)),
    ModelConfig("gemini-2.5-pro", "google", "gemini-2.5-pro", ("GOOGLE_API_KEY",)),
    ModelConfig("gemini-2.5-flash", "google", "gemini-2.5-flash", ("GOOGLE_API_KEY",)),
    ModelConfig("gemini-3.1-pro-preview", "google", "gemini-3.1-pro-preview",
                ("GOOGLE_API_KEY",)),
    ModelConfig("gemini-3-flash-preview", "google", "gemini-3-flash-preview",
                ("GOOGLE_API_KEY",)),
    ModelConfig("gemini-3.1-flash-lite", "google", "gemini-3.1-flash-lite",
                ("GOOGLE_API_KEY",)),
]


@dataclass
class CaseResult:
    case_id: str
    model_id: str
    passed: bool
    reason: str = ""
    elapsed_s: float = 0.0
    generated_sql: str | None = None
    response_type: str = ""
    response_content: str = ""
    error: str | None = None


def _select_models() -> list[ModelConfig]:
    requested = os.environ.get("BENCH_MODELS")
    if not requested:
        # Skip any model whose creds aren't present so the bench still
        # produces partial results without crashing.
        runnable: list[ModelConfig] = []
        for m in MODELS:
            if all(os.environ.get(k) for k in m.env_keys):
                runnable.append(m)
            else:
                print(f"[skip] {m.id} (missing {','.join(m.env_keys)})")
        return runnable
    wanted = {x.strip() for x in requested.split(",") if x.strip()}
    return [m for m in MODELS if m.id in wanted]


def _make_settings(model: ModelConfig) -> Settings:
    """Build a Settings object pointed at the given model."""
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
    return Settings(**overrides)


def _lower_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    return out


def _normalize_rows(
    df: pd.DataFrame, columns: list[str]
) -> set[tuple[Any, ...]]:
    """Normalize a result frame into a hashable comparison form.

    Caller is responsible for picking the column subset; this just coerces
    values into a stable form for set comparison.
    """
    if df is None or df.empty:
        return set()
    if columns:
        df = df[columns]
    rows: set[tuple[Any, ...]] = set()
    for _, row in df.iterrows():
        rows.add(tuple(_coerce(v) for v in row.tolist()))
    return rows


def _coerce(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 4)
    if pd.isna(v):
        return None
    return v


async def _execute(engine, sql: str) -> pd.DataFrame:
    async with engine.connect() as conn:
        result = await conn.execute(sqltext(sql))
        rows = result.fetchall()
        cols = list(result.keys())
    return pd.DataFrame(rows, columns=cols)


async def _grade(
    case: Case, response: Message, engine
) -> tuple[bool, str]:
    """Return (passed, reason)."""
    # Special-case: must NOT produce SQL.
    if case.expected_scalar == "__no_sql__":
        if response.sql_query:
            for pattern in case.must_not_contain_regex:
                if re.search(pattern, response.sql_query):
                    return False, f"produced disallowed SQL pattern {pattern!r}"
            # Producing SQL when none was expected is itself a fail.
            return False, "produced SQL for an out-of-domain prompt"
        return True, "no sql produced (expected)"

    if not response.sql_query:
        return False, f"no SQL generated; content={response.content[:140]!r}"

    sql = response.sql_query
    for pattern in case.must_contain_regex:
        if not re.search(pattern, sql):
            return False, f"generated SQL missing required pattern {pattern!r}"
    for pattern in case.must_not_contain_regex:
        if re.search(pattern, sql):
            return False, f"generated SQL contains forbidden pattern {pattern!r}"

    # Re-execute generated SQL against the DB to grade its actual rows
    # (ignore the LLM's natural-language summary, which can lie).
    try:
        actual = _lower_cols(await _execute(engine, sql))
    except Exception as e:
        return False, f"generated SQL did not execute: {e}"

    try:
        expected = _lower_cols(await _execute(engine, case.reference_sql))
    except Exception as e:
        return False, f"reference SQL failed (test bug): {e}"

    # Pick columns that exist on BOTH sides so the comparison is symmetric.
    # LLMs frequently rename "email" → "customer_email" or "sku" → "product_sku";
    # try a fuzzy match before declaring no overlap.
    def _match_col(target: str, candidates: list[str]) -> str | None:
        if target in candidates:
            return target
        # exact suffix or prefix match (e.g. customer_email matches email)
        for c in candidates:
            if c == target or c.endswith("_" + target) or c.startswith(target + "_"):
                return c
        # substring fallback
        for c in candidates:
            if target in c:
                return c
        return None

    actual_cols = list(actual.columns)
    expected_cols = list(expected.columns)

    if case.grade_columns:
        wanted = [c.lower() for c in case.grade_columns]
        actual_pick: list[str] = []
        expected_pick: list[str] = []
        missing: list[str] = []
        for w in wanted:
            a_c = _match_col(w, actual_cols)
            e_c = _match_col(w, expected_cols) or w
            if a_c is None:
                missing.append(w)
                continue
            actual_pick.append(a_c)
            expected_pick.append(e_c)
        if not actual_pick:
            return False, (
                f"no overlap between requested grade columns "
                f"{wanted} and actual columns {actual_cols}"
            )
        if missing:
            # Partial match — proceed on what we found, but flag it.
            pass
        actual = actual.rename(
            columns=dict(zip(actual_pick, [f"__g{i}" for i in range(len(actual_pick))]))
        )
        expected = expected.rename(
            columns=dict(
                zip(expected_pick, [f"__g{i}" for i in range(len(expected_pick))])
            )
        )
        cols = [f"__g{i}" for i in range(len(actual_pick))]
    else:
        cols = [c for c in expected_cols if c in actual_cols]
        if not cols:
            return False, (
                f"actual columns {actual_cols} do not overlap with reference "
                f"columns {expected_cols}"
            )

    a = _normalize_rows(actual, cols)
    e = _normalize_rows(expected, cols)

    if a == e:
        return True, f"rows match ({len(a)} rows on {cols})"

    missing = e - a
    extra = a - e
    msg_parts = [f"expected {len(e)} rows, got {len(a)}"]
    if missing:
        msg_parts.append(f"missing {len(missing)}: {list(missing)[:3]}")
    if extra:
        msg_parts.append(f"extra {len(extra)}: {list(extra)[:3]}")
    return False, "; ".join(msg_parts)


def _make_engine(settings: Settings):
    # Active connection metadata is read from the encrypted store the rest
    # of the app uses. For benching we just need the test DB engine for
    # grader-side execution; reuse the connection details from .env.
    db_user = os.environ.get("USERNAME", "testuser")
    db_pwd = os.environ.get("PASSWORD", "testpass")
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = int(os.environ.get("DB_PORT", "5433"))
    db_name = os.environ.get("DATABASE", "testdb")
    url = URL.create(
        "postgresql+asyncpg",
        username=db_user,
        password=db_pwd,
        host=db_host,
        port=db_port,
        database=db_name,
    )
    return create_async_engine(url, pool_pre_ping=True)


async def _run_one(
    case: Case, model: ModelConfig, message_service: MessageService, engine
) -> CaseResult:
    msgs: list[Message] = []
    for role, content in case.prior_turns:
        if role == "assistant_with_sql":
            msgs.append(
                Message(
                    role="assistant",
                    content="Previous result.",
                    type="sql",
                    sql_query="SELECT 1",
                )
            )
        else:
            msgs.append(Message(role=role, content=content, type="plain"))
    msgs.append(Message(role="user", content=case.prompt, type="plain"))

    started = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            message_service.process_messages(msgs), timeout=180
        )
    except asyncio.TimeoutError:
        return CaseResult(
            case.id,
            model.id,
            False,
            reason="timeout (>180s)",
            elapsed_s=time.perf_counter() - started,
            error="timeout",
        )
    except Exception as e:
        return CaseResult(
            case.id,
            model.id,
            False,
            reason=f"pipeline raised {type(e).__name__}",
            elapsed_s=time.perf_counter() - started,
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1000]}",
        )

    elapsed = time.perf_counter() - started
    passed, reason = await _grade(case, response, engine)
    return CaseResult(
        case_id=case.id,
        model_id=model.id,
        passed=passed,
        reason=reason,
        elapsed_s=elapsed,
        generated_sql=response.sql_query,
        response_type=response.type or "",
        response_content=(response.content or "")[:400],
    )


async def _bench_model(model: ModelConfig) -> list[CaseResult]:
    print(f"\n=== {model.id} ({model.provider}/{model.model_id}) ===")
    settings = _make_settings(model)

    # Spin up the metadata DB so embeddings have a place to land. Each
    # _bench_model call gets its own MetadataDB instance — bootstrap is
    # idempotent (CREATE … IF NOT EXISTS).
    metadata_db = MetadataDB(settings)
    await metadata_db.bootstrap()

    embedding_service = EmbeddingService(metadata_engine=metadata_db.engine)
    scanner_service = ScannerService(
        settings=settings,
        embedding_service=embedding_service,
        notification_callback=None,
    )

    message_service = MessageService(
        settings,
        scanner_service=scanner_service,
        metadata_engine=metadata_db.engine,
        embedding_service=embedding_service,
    )
    engine = _make_engine(settings)

    results: list[CaseResult] = []
    try:
        for case in CASES:
            r = await _run_one(case, model, message_service, engine)
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {case.id:38s} {r.elapsed_s:5.1f}s  {r.reason[:80]}")
            results.append(r)
    finally:
        await message_service.close()
        await scanner_service.close()
        await engine.dispose()
        await metadata_db.close()
    return results


def _write_report(run_dir: Path, all_results: dict[str, list[CaseResult]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    raw = {
        m_id: [asdict(r) for r in rs] for m_id, rs in all_results.items()
    }
    (run_dir / "raw.json").write_text(json.dumps(raw, indent=2, default=str))

    case_ids = [c.id for c in CASES]
    model_ids = list(all_results.keys())

    md_lines: list[str] = []
    md_lines.append(f"# NL→SQL Bench — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    md_lines.append("")
    md_lines.append("| Case | " + " | ".join(model_ids) + " |")
    md_lines.append("|" + "---|" * (len(model_ids) + 1))

    totals: dict[str, list[int]] = {m: [0, 0] for m in model_ids}
    avg_time: dict[str, list[float]] = {m: [] for m in model_ids}

    by_lookup: dict[tuple[str, str], CaseResult] = {}
    for m_id, rs in all_results.items():
        for r in rs:
            by_lookup[(r.case_id, m_id)] = r

    for cid in case_ids:
        row = [cid]
        for m_id in model_ids:
            r = by_lookup.get((cid, m_id))
            if r is None:
                row.append("—")
                continue
            mark = "✅" if r.passed else "❌"
            avg_time[m_id].append(r.elapsed_s)
            totals[m_id][0] += int(r.passed)
            totals[m_id][1] += 1
            row.append(f"{mark} {r.elapsed_s:.1f}s")
        md_lines.append("| " + " | ".join(row) + " |")

    md_lines.append("")
    md_lines.append("## Totals")
    md_lines.append("")
    md_lines.append("| Model | Pass | Total | Pass% | Avg latency |")
    md_lines.append("|---|---|---|---|---|")
    for m_id in model_ids:
        passed, total = totals[m_id]
        pct = (passed / total * 100) if total else 0.0
        latencies = avg_time[m_id]
        avg = sum(latencies) / len(latencies) if latencies else 0.0
        md_lines.append(
            f"| {m_id} | {passed} | {total} | {pct:.1f}% | {avg:.1f}s |"
        )

    md_lines.append("")
    md_lines.append("## Failures")
    for m_id in model_ids:
        for r in all_results[m_id]:
            if r.passed:
                continue
            md_lines.append(f"\n### {m_id} — {r.case_id}")
            md_lines.append(f"- reason: {r.reason}")
            if r.generated_sql:
                md_lines.append("- generated SQL:")
                md_lines.append("```sql")
                md_lines.append(r.generated_sql.strip())
                md_lines.append("```")
            if r.error:
                md_lines.append(f"- error: `{r.error[:300]}`")

    (run_dir / "report.md").write_text("\n".join(md_lines))
    print(f"\nReport: {run_dir / 'report.md'}")


async def main() -> int:
    models = _select_models()
    if not models:
        print("No runnable models — set OPENAI_API_KEY / ANTHROPIC_API_KEY / "
              "GOOGLE_API_KEY or BENCH_MODELS.")
        return 1

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = Path(__file__).resolve().parent / "results" / run_id

    all_results: dict[str, list[CaseResult]] = {}
    for m in models:
        try:
            all_results[m.id] = await _bench_model(m)
        except Exception as e:
            print(f"[fatal] {m.id}: {e}")
            traceback.print_exc()
            all_results[m.id] = [
                CaseResult(
                    case_id=c.id,
                    model_id=m.id,
                    passed=False,
                    reason="provider init failed",
                    error=str(e),
                )
                for c in CASES
            ]

    _write_report(run_dir, all_results)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
