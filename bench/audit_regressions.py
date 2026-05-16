"""Deep audit of the 98 pipeline regressions (bare-pass + pipe-fail).

Goal: cluster the failures by ROOT CAUSE so we know which fixes would
buy us back the most ground.

Categories we look for:
  - no_sql:            pipeline returned no SQL at all (retries exhausted)
  - missing_table:     pipeline's SQL didn't include a table the ref/bare uses
  - extra_table:       pipeline added an unnecessary table
  - wrong_limit:       pipeline used a different LIMIT than ref
  - wrong_aggregate:   different aggregation function (MAX vs MIN, COUNT vs SUM)
  - extra_columns:     pipeline returned more SELECT columns than ref
  - wrong_filter:      WHERE clause uses a wrong column or literal
  - wrong_order:       ORDER BY direction or column differs
  - case_quoting:      identifier case/quoting drift (e.g. "School Name")
  - extract_text_date: EXTRACT() on a text column without cast
  - other:             didn't match any pattern; needs human review
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

PIPE = "/Users/mary/text_to_sql/bench/results/bird_full_20260510_212541/raw.json"
BARE = "/Users/mary/text_to_sql/bench/results/bird_baseline_full_20260510_232535/raw.json"


def tables_in(sql: str) -> set[str]:
    if not sql:
        return set()
    return {
        m.group(1).lower()
        for m in re.finditer(r"\b(?:from|join)\s+\"?([A-Za-z_]\w*)\"?", sql, re.I)
    }


def select_cols_count(sql: str) -> int:
    """Crude SELECT column count — number of top-level commas + 1 in the
    first SELECT clause. Good enough for diagnostics."""
    if not sql:
        return 0
    m = re.search(r"select\s+(.*?)\s+from\b", sql, re.I | re.S)
    if not m:
        return 0
    sel = m.group(1)
    # Strip subqueries (parenthesized).
    depth = 0
    flat = []
    for c in sel:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            flat.append("|")
            continue
        flat.append(c)
    return len("".join(flat).split("|"))


def limit_value(sql: str) -> int | None:
    if not sql:
        return None
    m = re.search(r"\blimit\s+(\d+)\b", sql, re.I)
    return int(m.group(1)) if m else None


def has_order_by(sql: str) -> bool:
    return bool(sql and re.search(r"\border\s+by\b", sql, re.I))


def has_group_by(sql: str) -> bool:
    return bool(sql and re.search(r"\bgroup\s+by\b", sql, re.I))


def categorize(r_pipe: dict, r_bare: dict) -> str:
    """Pick one root-cause label for a single regression."""
    pipe_sql = r_pipe["generated_sql"] or ""
    ref_sql = r_pipe["reference_sql"] or ""
    bare_sql = r_bare["generated_sql"] or ""

    if not pipe_sql:
        return "no_sql"

    ref_t = tables_in(ref_sql)
    pipe_t = tables_in(pipe_sql)
    bare_t = tables_in(bare_sql)

    missing = ref_t - pipe_t
    extra_vs_ref = pipe_t - ref_t

    if missing:
        return "missing_table"
    if extra_vs_ref and len(extra_vs_ref) >= 1:
        return "extra_table"

    # LIMIT drift
    p_lim = limit_value(pipe_sql)
    r_lim = limit_value(ref_sql)
    if p_lim is not None and r_lim is not None and p_lim != r_lim:
        return "wrong_limit"
    if p_lim is None and r_lim is not None:
        return "wrong_limit"
    if p_lim is not None and r_lim is None and r_lim != p_lim:
        return "wrong_limit"

    # Column count drift in SELECT
    p_cols = select_cols_count(pipe_sql)
    r_cols = select_cols_count(ref_sql)
    if p_cols != r_cols and p_cols > 0 and r_cols > 0:
        if p_cols > r_cols:
            return "extra_columns"
        else:
            return "fewer_columns"

    # ORDER BY direction or presence
    if has_order_by(pipe_sql) != has_order_by(ref_sql):
        return "wrong_order"

    # GROUP BY presence
    if has_group_by(pipe_sql) != has_group_by(ref_sql):
        return "wrong_aggregate"

    # Aggregation function drift (MIN/MAX/COUNT/SUM/AVG)
    pipe_aggs = set(re.findall(r"\b(MIN|MAX|COUNT|SUM|AVG)\s*\(", pipe_sql, re.I))
    ref_aggs = set(re.findall(r"\b(MIN|MAX|COUNT|SUM|AVG)\s*\(", ref_sql, re.I))
    if pipe_aggs != ref_aggs and (pipe_aggs or ref_aggs):
        return "wrong_aggregate"

    # CASE-WHEN structure (often used in BIRD for conditional aggregation)
    pipe_case = len(re.findall(r"\bcase\s+when\b", pipe_sql, re.I))
    ref_case = len(re.findall(r"\bcase\s+when\b", ref_sql, re.I))
    if pipe_case != ref_case:
        return "missing_case_logic"

    # Same shape, different filter — probably wrong literal/column
    return "wrong_filter_or_value"


def main() -> int:
    pipe_run = json.loads(Path(PIPE).read_text())["gemini-2.5-flash"]
    bare_run = json.loads(Path(BARE).read_text())["gemini-2.5-flash"]
    pipe_by_q = {r["question_id"]: r for r in pipe_run}
    bare_by_q = {r["question_id"]: r for r in bare_run}

    qids = sorted(set(pipe_by_q) & set(bare_by_q))

    regressions = [
        q for q in qids
        if pipe_by_q[q]["ex"] == 0 and bare_by_q[q]["ex"] == 1
    ]
    rescues = [
        q for q in qids
        if pipe_by_q[q]["ex"] == 1 and bare_by_q[q]["ex"] == 0
    ]
    print(f"Regressions: {len(regressions)}, Rescues: {len(rescues)}\n")

    # Categorize regressions
    cats = Counter()
    by_cat: dict[str, list[int]] = defaultdict(list)
    for q in regressions:
        c = categorize(pipe_by_q[q], bare_by_q[q])
        cats[c] += 1
        by_cat[c].append(q)

    print("=== Regression root-cause distribution ===\n")
    for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
        pct = n / len(regressions) * 100
        print(f"  {cat:30s} {n:>3} ({pct:>5.1f}%)")
    print()

    # For each category, surface 1-2 examples
    print("=== Representative examples per category ===\n")
    for cat in sorted(cats, key=lambda c: -cats[c]):
        examples = by_cat[cat][:2]
        print(f"--- {cat} ({cats[cat]}) ---")
        for qid in examples:
            p = pipe_by_q[qid]
            b = bare_by_q[qid]
            print(f"  q{qid} ({p['db_id']}/{p['difficulty']})")
            print(f"    Q: {p['question'][:150]}")
            print(f"    PIPE: {(p['generated_sql'] or 'NULL').strip()[:180]}")
            print(f"    BARE: {b['generated_sql'].strip()[:180] if b['generated_sql'] else 'NULL'}")
            print(f"    REF:  {p['reference_sql'].strip()[:180]}")
        print()

    # Look at rescues — where does the pipeline currently HELP?
    print("=== Rescue cases (pipeline beats bare) — what kind? ===\n")
    rescue_cats = Counter()
    for q in rescues:
        # Use the same categorize, but bare is the failure here
        # Categorize bare's failure relative to ref
        b = bare_by_q[q]
        p = pipe_by_q[q]
        bare_sql = b["generated_sql"] or ""
        ref_sql = b["reference_sql"] or ""
        if not bare_sql:
            rescue_cats["bare_no_sql"] += 1
            continue
        ref_t = tables_in(ref_sql)
        bare_t = tables_in(bare_sql)
        if ref_t - bare_t:
            rescue_cats["bare_missing_table"] += 1
        else:
            rescue_cats["bare_wrong_sql_other"] += 1

    for c, n in rescue_cats.most_common():
        print(f"  {c:30s} {n}")
    print()

    # Sample 3 rescue cases
    print("3 rescue examples:")
    for qid in rescues[:3]:
        p = pipe_by_q[qid]
        b = bare_by_q[qid]
        print(f"  q{qid} ({p['db_id']}/{p['difficulty']})")
        print(f"    Q: {p['question'][:140]}")
        print(f"    PIPE (works): {(p['generated_sql'] or 'NULL').strip()[:160]}")
        print(f"    BARE (fails): {(b['generated_sql'] or 'NULL').strip()[:160]}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
