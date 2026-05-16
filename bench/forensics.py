"""Forensic analysis: where does the pipeline fail vs the bare baseline?

Cross-joins the per-question records from the pipeline-run and bare-
baseline-run raw.json files. The interesting cohort is bare_pass +
pipeline_fail: those are the regressions we caused. For each, we extract:

- Tables referenced by the reference SQL
- Tables in the pipeline's generated SQL
- Tables in the bare's generated SQL
- Which tables (if any) the pipeline failed to use

That tells us whether the regression is upstream (retrieval missed
required tables) or downstream (we had the right tables but generated
worse SQL).
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

PIPELINE_DIR = Path(
    "/Users/mary/text_to_sql/bench/results/bird_full_20260510_212541"
)
BASELINE_DIR = Path(
    "/Users/mary/text_to_sql/bench/results/bird_baseline_full_20260510_232535"
)


def extract_tables(sql: str) -> set[str]:
    """Pull out lower-cased table names from FROM / JOIN clauses."""
    if not sql:
        return set()
    tables: set[str] = set()
    for m in re.finditer(
        r"\b(?:from|join)\s+\"?([A-Za-z_][\w]*)\"?", sql, re.IGNORECASE
    ):
        tables.add(m.group(1).lower())
    return tables


def main() -> int:
    pipe = {
        r["question_id"]: r
        for r in json.loads((PIPELINE_DIR / "raw.json").read_text())["gemini-2.5-flash"]
    }
    bare = {
        r["question_id"]: r
        for r in json.loads((BASELINE_DIR / "raw.json").read_text())["gemini-2.5-flash"]
    }

    qids = sorted(set(pipe) & set(bare))
    cross = Counter()
    for qid in qids:
        p = pipe[qid]["ex"] == 1
        b = bare[qid]["ex"] == 1
        cross[("pipe_pass" if p else "pipe_fail",
               "bare_pass" if b else "bare_fail")] += 1

    print("=== Cross-tab (n=500) ===")
    print(f"{'':<14}{'bare_pass':>12}{'bare_fail':>12}")
    print(f"{'pipe_pass':<14}{cross[('pipe_pass','bare_pass')]:>12}{cross[('pipe_pass','bare_fail')]:>12}")
    print(f"{'pipe_fail':<14}{cross[('pipe_fail','bare_pass')]:>12}{cross[('pipe_fail','bare_fail')]:>12}")
    print()

    pipe_only_pass = cross[("pipe_pass", "bare_fail")]
    bare_only_pass = cross[("pipe_fail", "bare_pass")]
    both_pass = cross[("pipe_pass", "bare_pass")]
    both_fail = cross[("pipe_fail", "bare_fail")]
    print(f"Both pass:                  {both_pass} ({both_pass/5:.1f}%)")
    print(f"Bare-only pass (pipe broke this): {bare_only_pass} ({bare_only_pass/5:.1f}%)  <-- regressions")
    print(f"Pipe-only pass (pipe rescued):    {pipe_only_pass} ({pipe_only_pass/5:.1f}%)")
    print(f"Both fail:                  {both_fail} ({both_fail/5:.1f}%)")
    print()

    # Focus on regressions: bare_pass, pipe_fail.
    regressions = [
        (qid, pipe[qid], bare[qid]) for qid in qids
        if bare[qid]["ex"] == 1 and pipe[qid]["ex"] == 0
    ]
    print(f"=== Regression analysis (n={len(regressions)}) ===\n")

    # Categorize each regression by failure mode.
    no_sql = 0
    sql_executed_but_wrong = 0
    missing_required_table = 0
    same_table_set_diff_sql = 0
    table_count_mismatch = []

    pipe_table_counts = []
    bare_table_counts = []
    ref_table_counts = []

    fail_reasons = Counter()

    for qid, p, b in regressions:
        ref_tables = extract_tables(p["reference_sql"] or "")
        pipe_tables = extract_tables(p["generated_sql"] or "")
        bare_tables = extract_tables(b["generated_sql"] or "")

        ref_table_counts.append(len(ref_tables))
        pipe_table_counts.append(len(pipe_tables))
        bare_table_counts.append(len(bare_tables))

        if not p["generated_sql"]:
            no_sql += 1
            fail_reasons["no SQL generated (pipeline)"] += 1
            continue

        sql_executed_but_wrong += 1
        missing = ref_tables - pipe_tables
        if missing:
            missing_required_table += 1
            fail_reasons[f"missing table(s) from required set: e.g. {sorted(missing)[:3]}"] += 1
        elif pipe_tables == bare_tables:
            same_table_set_diff_sql += 1
            fail_reasons["same tables as bare, but SQL differs"] += 1
        else:
            fail_reasons["had required tables but used different set than bare"] += 1

    print(f"  Pipeline returned NO SQL:       {no_sql:>3} ({no_sql / len(regressions) * 100:.1f}%)")
    print(f"  SQL ran but wrong:              {sql_executed_but_wrong:>3} ({sql_executed_but_wrong / len(regressions) * 100:.1f}%)")
    print(f"    — missing required table:     {missing_required_table:>3} ({missing_required_table / len(regressions) * 100:.1f}%)")
    print(f"    — same tables, worse SQL:     {same_table_set_diff_sql:>3} ({same_table_set_diff_sql / len(regressions) * 100:.1f}%)")
    print()

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0

    print("Avg tables in reference SQL (regression set):  "
          f"{avg(ref_table_counts):.1f}")
    print("Avg tables in pipeline's SQL  (regression set):"
          f" {avg(pipe_table_counts):.1f}")
    print("Avg tables in bare's SQL      (regression set):"
          f" {avg(bare_table_counts):.1f}")
    print()

    # Sample 5 specific regressions across categories.
    print("=== 5 representative regressions ===\n")
    samples_shown = 0
    seen_buckets = set()
    for qid, p, b in regressions:
        if samples_shown >= 8:
            break
        ref_tables = extract_tables(p["reference_sql"] or "")
        pipe_tables = extract_tables(p["generated_sql"] or "")
        bucket = (
            "no_sql" if not p["generated_sql"]
            else ("missing_table" if (ref_tables - pipe_tables) else "same_tables")
        )
        if bucket in seen_buckets and samples_shown >= 3:
            continue
        seen_buckets.add(bucket)
        samples_shown += 1
        print(f"--- q{qid} ({p['db_id']}/{p['difficulty']}) bucket={bucket} ---")
        print(f"  Q: {p['question'][:200]}")
        print(f"  REF tables: {sorted(ref_tables)}")
        if p['generated_sql']:
            print(f"  PIPE tables: {sorted(pipe_tables)}  | F1={p['soft_f1']:.2f}")
            print(f"  PIPE SQL: {p['generated_sql'].strip()[:220]}")
        else:
            print(f"  PIPE: NO SQL (reason: {p['reason'][:100]})")
        if b['generated_sql']:
            print(f"  BARE SQL: {b['generated_sql'].strip()[:220]}")
        print()

    # Per-DB regression count
    print("=== Regressions by db_id ===")
    by_db = Counter(p["db_id"] for _, p, _ in regressions)
    for db, n in by_db.most_common():
        print(f"  {db:32s}: {n} regressions")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
