"""Bare-model baseline runner for BIRD Mini-Dev.

Single LLM call per question. No vector retrieval, no agent
orchestration, no retry loop, no correction prompt. The model gets:

  1. BIRD's canonical schema for the question's db_id
     (from dev_tables.json, the same source the leaderboard uses)
  2. The natural-language question
  3. The evidence/hint string (Oracle Knowledge — matches BIRD methodology)

…and is asked for one PostgreSQL SELECT statement. Whatever it returns
gets executed against the same `bird_dev` Postgres and graded with the
BIRD-official EX + Soft F1 (same grader as bird_runner.py).

The purpose is honest attribution: separating what the model itself can
do from what our pipeline adds on top.

Usage::

    BENCH_MODELS=gemini-2.5-flash uv run python -m bench.bird_baseline --all
    BENCH_MODELS=gemini-2.5-flash uv run python -m bench.bird_baseline --max-queries 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env", override=True)

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from bench.bird_loader import (  # noqa: E402
    BIRD_PG_DATABASE,
    BIRD_QUESTIONS_JSON,
    BIRD_UNZIPPED_DIR,
    HOST_BIND_ADDRESS,
    HOST_PASSWORD,
    HOST_PORT,
    HOST_USER,
)
from bench.bird_runner import (  # noqa: E402
    BirdQuestion,
    PRICING,
    TokenCounter,
    _calculate_ex,
    _calculate_soft_f1,
    _execute,
    _row_to_jsonable,
)
from bench.run_bench import MODELS, ModelConfig  # noqa: E402
from src.common.settings import Settings  # noqa: E402

DEV_TABLES_JSON = BIRD_UNZIPPED_DIR / "MINIDEV" / "dev_tables.json"


# ---- Schema rendering from BIRD's canonical metadata ------------------


def load_schemas() -> dict[str, str]:
    """Return `{db_id: prompt-ready schema string}` built from BIRD's
    dev_tables.json. Format matches what BIRD's official runner shows
    each model: tables with typed columns and foreign keys."""
    raw = json.loads(DEV_TABLES_JSON.read_text())
    out: dict[str, str] = {}
    for entry in raw:
        out[entry["db_id"]] = _render_schema(entry)
    return out


def _render_schema(entry: dict) -> str:
    tables = entry["table_names_original"]
    cols = entry["column_names_original"]
    types = entry["column_types"]
    fks = entry.get("foreign_keys", []) or []

    # Group columns by table index. column_names_original[i] = [tbl_idx, col_name].
    by_table: dict[int, list[tuple[str, str]]] = {i: [] for i in range(len(tables))}
    for i, (tbl_idx, col_name) in enumerate(cols):
        if tbl_idx == -1:
            continue  # `*` placeholder
        by_table[tbl_idx].append((col_name, types[i]))

    parts: list[str] = []
    for idx, tname in enumerate(tables):
        col_strs = ", ".join(f"{c} ({t})" for c, t in by_table.get(idx, []))
        parts.append(f"Table {tname}:\n  {col_strs}")

    if fks:
        fk_lines = []
        for left_col_idx, right_col_idx in fks:
            l_tbl, l_col = cols[left_col_idx]
            r_tbl, r_col = cols[right_col_idx]
            if l_tbl == -1 or r_tbl == -1:
                continue
            fk_lines.append(
                f"  {tables[l_tbl]}.{l_col} -> {tables[r_tbl]}.{r_col}"
            )
        if fk_lines:
            parts.append("Foreign keys:\n" + "\n".join(fk_lines))

    return "\n\n".join(parts)


# ---- Bare prompt for the model ----------------------------------------


SYSTEM_PROMPT = """You are an expert PostgreSQL query writer.
You will be given a database schema, a natural-language question, and
optional domain knowledge ("evidence"). Generate exactly one PostgreSQL
SELECT statement that answers the question. Use only the tables and
columns shown. Output strict JSON: {"sql_query": "<your SELECT>"}.
Return nothing else."""


def build_user_prompt(schema: str, question: str, evidence: str) -> str:
    parts = ["Schema:", schema, "", f"Question: {question}"]
    if evidence:
        parts.append(f"Evidence: {evidence}")
    parts.append("\nReturn only a JSON object with key 'sql_query'.")
    return "\n".join(parts)


# ---- SQL extraction --------------------------------------------------


def extract_sql(content: str) -> str | None:
    """Pull a SQL query out of the model's response text."""
    content = content.strip()
    # 1. JSON path.
    try:
        m = re.search(r"\{.*\"sql_query\".*\}", content, re.DOTALL)
        if m:
            obj = json.loads(m.group(0))
            sql = obj.get("sql_query")
            if sql and isinstance(sql, str):
                return sql.strip()
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. ```sql fenced block.
    m = re.search(r"```(?:sql)?\s*([\s\S]+?)```", content, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # 3. Raw SELECT/WITH at start.
    if re.match(r"^\s*(SELECT|WITH)\b", content, re.IGNORECASE):
        return content.strip()

    return None


# ---- Result record ---------------------------------------------------


@dataclass
class BaselineResult:
    question_id: int
    db_id: str
    difficulty: str
    model: str
    ex: int = 0
    soft_f1: float = 0.0
    passed: bool = False
    reason: str = ""
    elapsed_s: float = 0.0
    generated_sql: str | None = None
    reference_sql: str | None = None
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


# ---- Runner ----------------------------------------------------------


def _make_llm(model: ModelConfig):
    """Direct LangChain client for the chosen model — no pipeline wiring."""
    s = Settings()  # picks up API keys from env via the same machinery.
    if model.provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model.model_id,
            google_api_key=os.environ["GOOGLE_API_KEY"],
            temperature=0.0,
            max_output_tokens=2048,
        )
    if model.provider == "openai":
        from langchain_openai import ChatOpenAI
        kwargs = dict(
            model=model.model_id,
            api_key=os.environ["OPENAI_API_KEY"],
            temperature=0.0,
        )
        # gpt-3.5-turbo caps completion tokens at 4096.
        kwargs["max_tokens"] = 4096 if model.id == "gpt-3.5-turbo" else 2048
        return ChatOpenAI(**kwargs)
    if model.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model.model_id,
            api_key=os.environ["ANTHROPIC_API_KEY"],
            temperature=0.0,
            max_tokens=2048,
        )
    raise ValueError(f"Unsupported provider {model.provider!r}")


async def run_one(
    q: BirdQuestion,
    model: ModelConfig,
    llm,
    schema_text: str,
    counter: TokenCounter,
    db_engine,
) -> BaselineResult:
    counter.reset()
    started = time.perf_counter()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=build_user_prompt(schema_text, q.question, q.evidence)),
    ]
    try:
        resp = await asyncio.wait_for(
            llm.ainvoke(messages, config={"callbacks": [counter]}),
            timeout=120,
        )
    except asyncio.TimeoutError:
        return BaselineResult(
            question_id=q.question_id, db_id=q.db_id, difficulty=q.difficulty,
            model=model.id, reason="LLM call timeout (>120s)",
            elapsed_s=time.perf_counter() - started, error="timeout",
            reference_sql=q.SQL, question=q.question, evidence=q.evidence,
        )
    except Exception as e:
        return BaselineResult(
            question_id=q.question_id, db_id=q.db_id, difficulty=q.difficulty,
            model=model.id, reason=f"LLM error: {type(e).__name__}",
            elapsed_s=time.perf_counter() - started,
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[:600]}",
            reference_sql=q.SQL, question=q.question, evidence=q.evidence,
        )

    elapsed = time.perf_counter() - started
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    sql = extract_sql(raw)

    if not sql:
        return BaselineResult(
            question_id=q.question_id, db_id=q.db_id, difficulty=q.difficulty,
            model=model.id, reason="no SQL extracted from response",
            elapsed_s=elapsed,
            input_tokens=counter.input_tokens, output_tokens=counter.output_tokens,
            cost_usd=_cost(model, counter),
            reference_sql=q.SQL, question=q.question, evidence=q.evidence,
        )

    # Grade against the same Postgres BIRD uses on its leaderboard.
    try:
        actual = await _execute(db_engine, sql)
    except Exception as e:
        return BaselineResult(
            question_id=q.question_id, db_id=q.db_id, difficulty=q.difficulty,
            model=model.id, reason=f"generated SQL did not execute: {str(e)[:100]}",
            elapsed_s=elapsed,
            generated_sql=sql, reference_sql=q.SQL,
            input_tokens=counter.input_tokens, output_tokens=counter.output_tokens,
            cost_usd=_cost(model, counter), error=str(e)[:500],
            question=q.question, evidence=q.evidence,
        )
    try:
        expected = await _execute(db_engine, q.SQL)
    except Exception as e:
        return BaselineResult(
            question_id=q.question_id, db_id=q.db_id, difficulty=q.difficulty,
            model=model.id, reason=f"reference SQL failed (BIRD-side bug): {e}",
            elapsed_s=elapsed,
            generated_sql=sql, reference_sql=q.SQL,
            input_tokens=counter.input_tokens, output_tokens=counter.output_tokens,
            cost_usd=_cost(model, counter),
            question=q.question, evidence=q.evidence,
        )

    ex = _calculate_ex(actual, expected)
    f1 = _calculate_soft_f1(actual, expected)
    return BaselineResult(
        question_id=q.question_id, db_id=q.db_id, difficulty=q.difficulty,
        model=model.id, ex=ex, soft_f1=f1, passed=(ex == 1),
        reason=(
            f"EX=1, F1=1.00 ({len(expected)} rows)" if ex == 1
            else f"EX=0, F1={f1:.2f} | actual={len(actual)} / expected={len(expected)} rows"
        ),
        elapsed_s=elapsed,
        generated_sql=sql, reference_sql=q.SQL,
        generated_rows=[_row_to_jsonable(r) for r in actual],
        expected_rows=[_row_to_jsonable(r) for r in expected],
        generated_row_count=len(actual), expected_row_count=len(expected),
        input_tokens=counter.input_tokens, output_tokens=counter.output_tokens,
        cost_usd=_cost(model, counter),
        question=q.question, evidence=q.evidence,
    )


def _cost(model: ModelConfig, counter: TokenCounter) -> float:
    in_price, out_price = PRICING.get(model.id, (0.0, 0.0))
    return (
        counter.input_tokens / 1e6 * in_price
        + counter.output_tokens / 1e6 * out_price
    )


def _bird_engine():
    url = URL.create(
        "postgresql+asyncpg",
        username=HOST_USER, password=HOST_PASSWORD,
        host=HOST_BIND_ADDRESS, port=HOST_PORT,
        database=BIRD_PG_DATABASE,
    )
    return create_async_engine(url, pool_pre_ping=True)


def _select_models() -> list[ModelConfig]:
    requested = os.environ.get("BENCH_MODELS")
    if not requested:
        return [m for m in MODELS if all(os.environ.get(k) for k in m.env_keys)]
    wanted = {x.strip() for x in requested.split(",") if x.strip()}
    return [m for m in MODELS if m.id in wanted]


def _load_questions() -> list[BirdQuestion]:
    raw = json.loads(BIRD_QUESTIONS_JSON.read_text())
    return [BirdQuestion(**q) for q in raw]


def _aggregate(rs: list[BaselineResult]) -> dict:
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
    model_results: dict[str, list[BaselineResult]],
    config: dict,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    raw = {m: [asdict(r) for r in rs] for m, rs in model_results.items()}
    (run_dir / "raw.json").write_text(json.dumps(raw, indent=2, default=str))

    summary = {"config": config, "models": {}}
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

    lines = [
        f"# BIRD Mini-Dev — BARE MODEL BASELINE — "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "Single LLM call per question. No vector retrieval, no agent loop, "
        "no retry, no correction. BIRD's canonical schema from dev_tables.json.",
        "",
        "## EX (Execution Accuracy)\n",
        "| Model | Simple | Moderate | Challenging | **Total** |",
        "|---|---|---|---|---|",
    ]
    for model_id, rs in model_results.items():
        agg = _aggregate(rs)
        cells = [model_id]
        for bucket in ("simple", "moderate", "challenging", "total"):
            d = agg[bucket]
            cells.append(f"{d['ex']:.2f} ({d['count']})" if d["count"] else "—")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("\n## Soft F1\n")
    lines.append("| Model | Simple | Moderate | Challenging | **Total** |")
    lines.append("|---|---|---|---|---|")
    for model_id, rs in model_results.items():
        agg = _aggregate(rs)
        cells = [model_id]
        for bucket in ("simple", "moderate", "challenging", "total"):
            d = agg[bucket]
            cells.append(f"{d['soft_f1']:.2f} ({d['count']})" if d["count"] else "—")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("\n## Cost & tokens\n")
    lines.append("| Model | In/Out tokens | Avg/Q | Avg latency | Logged cost |")
    lines.append("|---|---|---|---|---|")
    for model_id, rs in model_results.items():
        m = summary["models"][model_id]
        lines.append(
            f"| {model_id} | {m['input_tokens']}/{m['output_tokens']} | "
            f"{m['avg_input_tokens_per_q']:.0f}/{m['avg_output_tokens_per_q']:.0f} | "
            f"{m['avg_elapsed_s']:.1f}s | ${m['cost_usd']:.3f} |"
        )

    lines.append("\n## Per-DB EX\n")
    lines.append("| DB | " + " | ".join(model_results.keys()) + " |")
    lines.append("|" + "---|" * (len(model_results) + 1))
    all_dbs: set[str] = set()
    for rs in model_results.values():
        all_dbs.update(r.db_id for r in rs)
    for db in sorted(all_dbs):
        cells = [db]
        for model_id, rs in model_results.items():
            sub = [r for r in rs if r.db_id == db]
            if not sub:
                cells.append("—")
                continue
            p = sum(r.ex for r in sub)
            cells.append(f"{p / len(sub) * 100:.0f} ({p}/{len(sub)})")
        lines.append("| " + " | ".join(cells) + " |")

    (run_dir / "report.md").write_text("\n".join(lines))
    print(f"\nReport: {run_dir / 'report.md'}")
    print(f"Metrics: {run_dir / 'metrics.json'}")
    print(f"Raw: {run_dir / 'raw.json'}")


async def run_model(
    model: ModelConfig,
    questions: list[BirdQuestion],
    schemas: dict[str, str],
) -> list[BaselineResult]:
    print(f"\n=== {model.id} (bare baseline) ===")
    llm = _make_llm(model)
    counter = TokenCounter()
    db_engine = _bird_engine()
    results: list[BaselineResult] = []
    try:
        for q in questions:
            schema = schemas.get(q.db_id, "")
            if not schema:
                results.append(BaselineResult(
                    question_id=q.question_id, db_id=q.db_id,
                    difficulty=q.difficulty, model=model.id,
                    reason=f"no schema for db_id {q.db_id!r}",
                    reference_sql=q.SQL,
                ))
                continue
            r = await run_one(q, model, llm, schema, counter, db_engine)
            status = "PASS" if r.ex == 1 else "FAIL"
            print(
                f"  [{status}] q{r.question_id:5d} {r.difficulty[:4]:4s} "
                f"{r.db_id[:18]:18s} EX={r.ex} F1={r.soft_f1:.2f} "
                f"{r.elapsed_s:5.1f}s in={r.input_tokens:5d} "
                f"out={r.output_tokens:4d} ${r.cost_usd:.4f}  {r.reason[:40]}"
            )
            results.append(r)
    finally:
        await db_engine.dispose()
    return results


async def main() -> int:
    parser = argparse.ArgumentParser(description="BIRD Mini-Dev bare baseline")
    parser.add_argument("--all", action="store_true",
                        help="Run every Mini-Dev question (500 total).")
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not BIRD_QUESTIONS_JSON.exists():
        print(f"Questions missing at {BIRD_QUESTIONS_JSON}.", file=sys.stderr)
        return 2
    if not DEV_TABLES_JSON.exists():
        print(f"dev_tables.json missing at {DEV_TABLES_JSON}.", file=sys.stderr)
        return 2

    schemas = load_schemas()
    questions = _load_questions()
    if args.all:
        sampled = list(questions)
    else:
        # Default to first 30 simple-difficulty for fast smoke.
        sampled = [q for q in questions if q.difficulty == "simple"][:30]
    if args.max_queries is not None:
        sampled = sampled[: args.max_queries]

    diff_hist = Counter(q.difficulty for q in sampled)
    db_hist = Counter(q.db_id for q in sampled)
    print(f"Sampled {len(sampled)} questions: {dict(diff_hist)}")

    models = _select_models()
    if not models:
        print("No runnable models.", file=sys.stderr)
        return 1

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tier_label = "full" if args.all else "smoke"
    run_dir = REPO_ROOT / "bench" / "results" / f"bird_baseline_{tier_label}_{run_id}"

    config = {
        "run_id": run_id,
        "tier": tier_label,
        "models": [m.id for m in models],
        "sampled_count": len(sampled),
        "difficulty_histogram": dict(diff_hist),
        "db_histogram": dict(db_hist),
        "question_ids": [q.question_id for q in sampled],
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "grader": "BIRD-official EX + Soft F1",
        "pipeline": "BARE — single LLM call, no retrieval/retries/correction",
        "schema_source": "BIRD dev_tables.json (canonical, leaderboard methodology)",
    }

    model_results: dict[str, list[BaselineResult]] = {}
    for m in models:
        try:
            model_results[m.id] = await run_model(m, sampled, schemas)
        except Exception as e:
            print(f"[fatal] {m.id}: {e}")
            traceback.print_exc()
            model_results[m.id] = []

    config["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_report(run_dir, model_results, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
