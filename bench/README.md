# NL → SQL Bench

Comparative benchmark for LLM models running through the full Text2SQL
pipeline (vector table search → schema-aware prompt → SQL gen →
execution → self-correction loop). Each model's generated SQL is
re-executed against the test DB and the rows are compared to a fixed
reference query.

## What's tested

`bench/queries.py` holds 13 cases covering:

- Aggregates with status enum filtering
- LEFT JOIN / `NOT EXISTS` anti-joins
- `CASE` bucketing with aggregates
- `EXISTS` / `NOT EXISTS` set semantics over a category hierarchy
- `COUNT(col)` vs `COUNT(*)` for NULL handling
- `RANK() OVER (PARTITION BY ...)` with tie handling
- `NOW() - INTERVAL '30 days'` date math
- Out-of-domain question (must not produce SQL)
- Unknown table (must refuse)
- Destructive request (must refuse)
- `AVG() OVER ()` global window
- Russian prompt
- Russian follow-up that requires conversation context

## Prerequisites

1. Test database running on `localhost:5433`:
   ```bash
   docker compose -f docker-compose.test.yml up -d
   ```
2. The `e2e-test` connection saved & active (already seeded into
   `data/connections.enc`).
3. API keys for the models you want to compare, in `.env`:
   ```dotenv
   OPENAI_API_KEY=sk-...
   ANTHROPIC_API_KEY=sk-ant-...
   GOOGLE_API_KEY=...
   ```
   Models whose key is missing are silently skipped.

## Models

`bench/run_bench.py` ships with a default matrix:

| id | provider | model_id |
|---|---|---|
| gpt-4o-mini | openai | gpt-4o-mini |
| gpt-4o | openai | gpt-4o |
| claude-sonnet-4-5 | anthropic | claude-sonnet-4-5 |
| gemini-2.5-pro | google | gemini-2.5-pro |
| gemini-2.5-flash | google | gemini-2.5-flash |

To override, set `BENCH_MODELS=...` to a comma-separated list of `id`s,
or edit the `MODELS` list in `run_bench.py` to add/replace entries.

## Run

```bash
uv run python -m bench.run_bench
# or only some models
BENCH_MODELS=gemini-2.5-pro,claude-sonnet-4-5 uv run python -m bench.run_bench
```

Results go to `bench/results/<timestamp>/`:
- `report.md` — human-readable matrix + per-failure SQL dump
- `raw.json` — every case × model with timings, generated SQL, etc.

## How grading works

1. **Out-of-domain / safety cases** (`expected_scalar="__no_sql__"`) pass
   if the pipeline returns a plain message with no `sql_query`. They
   fail if SQL is generated.
2. **Data cases** re-execute the model's SQL and the case's
   `reference_sql`, then compare the resulting row sets.
   - Column names are normalized to lowercase, then a fuzzy match maps
     LLM aliases (`product_sku` → `sku`, `customer_email` → `email`).
   - Comparison is set-based by default. Set `ordered=True` on a case
     to require row order — but the current grader still compares as a
     set; ordering is enforced indirectly via window/LIMIT clauses
     where it matters.
   - `must_contain_regex` / `must_not_contain_regex` add structural
     assertions on the generated SQL itself (e.g. "must use `RANK()`").

## Adding new cases

Append a `Case(...)` to `CASES` in `bench/queries.py` with:
- `prompt`: the natural-language question
- `reference_sql`: a known-good SQL that returns the truth set
- `grade_columns`: which columns to compare (subset of reference cols)
- optional `must_contain_regex` for structural checks

Re-run; failing cases will dump the generated SQL into `report.md` so
you can quickly diagnose.
