# Task 4 — CSV Analytical "Killer Demo" Design

**Date:** 2026-06-11
**Status:** approved (brainstorming) — ready for implementation plan

## Goal

Demonstrate the benchmark's headline finding: when an agent answers analytical
questions over a tabular dataset, the **naive** approach (CSV in the LLM
context) explodes in tokens/cost as rows grow and eventually breaks, while the
**expert** approach (a SQL tool, data out of context) stays flat. The gap
between those two curves is the chart the whitepaper and pitch deck are built
on.

## Measurement unit

One **run** = `(framework, strategy, size)` where:
- `strategy ∈ {naive, expert}`
- `size ∈ {S, M, L}` (XL deferred)

In each run the agent receives **all 20 questions** (`questions_20.json`) and
access to the dataset, and must return a JSON object mapping question id →
answer: `{"Q01": 500, "Q06": {...}, ...}`.

Metrics per run: total tokens (proxy-authoritative), latency, USD cost,
`ram_peak_mb`, and **`success_rate` = (# of 20 answers correct) / 20**.

Rationale: "all 20 in one run" measures the realistic cost of analyzing a
dataset and yields the tokens-vs-rows curve directly, instead of 20× the runs.

## Strategies

### Naive
The full CSV text is injected into the prompt (instructions + 20 questions +
CSV). The agent reasons over raw rows. Tokens scale with rows:
- S (44 KB ≈ ~11k tokens): fits comfortably.
- M (438 KB ≈ ~110k tokens): expensive, fits.
- L (4.4 MB ≈ ~1.1M tokens): **exceeds gemini-2.5-flash's 1M context →
  expected hard failure.** This failure is a deliverable: the runner catches
  it and emits a run with `success.ok=false` and an `error`/reason recording
  the failure mode (context overflow or provider rejection). The chart shows
  naive fl-lining/breaking at L.

### Expert
The agent gets exactly one tool, `run_sql(query: str) -> str`, backed by the
CSV loaded into an in-memory SQLite table named `orders` (schema = the CSV
columns). The CSV is **not** in context. The agent writes one or more SQL
queries per question. Tokens scale with questions, ~flat across sizes.

The SQLite-loading helper is shared (framework-agnostic): given a CSV path,
create an in-memory DB with table `orders` and return a `run_sql` callable.
Each framework wraps that callable as its native tool type.

## Output & scoring

**The runner never sees the ground truth** (prevents cheating; centralizes
scoring). Flow:
1. Runner produces `answer` = the 20-answer dict (parsed from the agent's
   final message; if the agent emits prose around JSON, extract the JSON
   object). `success` is left deferred (`{"ok": false, "reason": "scored
   externally"}`).
2. The orchestrator, after enriching tokens from proxy spans, scores Task 4
   runs with a new **`harness/scoring/task04_scorer.py`** against
   `ground_truth.json` for that variant's size, then overwrites `success` and
   records a per-question breakdown in `extras`.

`success` semantics for Task 4 (explicit, to avoid ambiguity):
- `success.ok` = **the run completed and produced a parseable 20-answer
  dict** (i.e. didn't crash, time out, or overflow context). A naive-L run
  that overflows → `ok=false`. A run that completes with 14/20 correct →
  `ok=true`. This separates "did it run" from "how correct".
- `success.judge_score` = **`success_rate` = correct / 20** (continuous;
  the headline correctness metric for the report/charts).
- A run that errored before producing answers → `ok=false`,
  `judge_score=0.0`, `error` set.

### Scorer comparison rules (per answer_type in questions_20.json)
- `integer`: parse int from the answer; exact match.
- `float`: parse float; pass if within **1% relative** tolerance (SQL results
  should be near-exact; tolerance absorbs rounding/formatting).
- `date`: ISO string equality after trimming.
- `object` (dict, e.g. per-country sums): compare on the **intersection of
  keys**; every shared key's value must match by the numeric (1%) or string
  rule; fail if either side is missing >0 keys the other has. Record missing
  keys in the breakdown.
- `object_top_n`: same as object but only the top-N keys are required.
- `array` (e.g. top-5 product ids): order-sensitive list equality. Document
  that LLM tie-ordering may cause misses; this is a real measured difficulty,
  not a scorer bug.

The scorer must robustly parse answers that arrive as strings (e.g. `"500"`,
`"$1,124,383.23"`) — strip currency/commas/whitespace before numeric compare.

## Task definitions & dataset wiring

Two task YAMLs (fits the runner contract with no CLI change — strategy is the
task id, size is the variant):

- `harness/tasks/04_csv_naive.yaml` — variants S/M/L, each variant's
  `dataset_path` → `data/orders_synthetic/seeds/{S,M,L}.csv`.
- `harness/tasks/04_csv_expert.yaml` — same variants/datasets.

Both declare `success.kind: dataset_qa` (a new sentinel meaning "scored
externally by the orchestrator"). Add `dataset_qa` to the task schema's
`success.kind` enum and document that runners must not score it.

The orchestrator runs both task ids across the chosen frameworks/sizes and the
report compares naive vs expert per size.

## Runner structure

Each framework runner gains two handlers, registered by task id:
- `tasks/task04_naive.py` → builds the big prompt, one LLM call, parse JSON.
- `tasks/task04_expert.py` → builds the agent + `run_sql` tool, runs the
  agent loop, parse JSON.

Shared, framework-agnostic helpers live in `bench_common`:
- `bench_common.datasets.load_orders_sqlite(csv_path)` → `(conn, run_sql)`.
- `bench_common.datasets.read_csv_text(csv_path)` → str (for naive).
- `bench_common.answers.extract_answer_dict(text)` → dict (tolerant JSON
  extraction from a model message).

The variant's `dataset_path` is resolved by the runner from the task YAML's
`variants` entry matching `--variant`; the runner reads the CSV relative to
the repo root.

## MVP scope (this implementation cycle)

Deliver the asymptote + scorer end-to-end on:
- **CrewAI**: naive **and** expert, sizes S/M/L (full curve, both strategies).
- **Colmena**: naive only, sizes S/M/L (easy — single `ColmenaLlm.call`).

**Deferred to the immediate next cycle (own plan):** Colmena **expert**, which
needs Colmena's agentic tool-calling (a `runDag` DAG with a tool node) rather
than the single-shot `ColmenaLlm.call` used so far — materially more complex
than the Python frameworks' `@tool` wiring. Then the remaining four frameworks
(naive + expert), then T26 charts, then XL.

Rationale: this proves the entire machine — both strategies, the SQLite tool,
the deferred scorer, the tokens-vs-rows break at L — without getting blocked on
Colmena's DAG tool API.

## Cost & N

Task 4 runs are far more expensive than Task 1. Use small N (default **N=3**;
**N=1 for naive-L** since it's an expected hard failure). At gemini-2.5-flash
$0.30/1M input, one naive-M run is ~110k input tokens ≈ $0.03; naive-L is
rejected for context overflow (cheap failure) — log the failure mode rather
than forcing a 1M-token bill. The orchestrator must tolerate a run that errors
out and still record it (it already does).

## Charts (downstream, T26 — not in this cycle)
Once naive vs expert data exists across sizes, four charts get generated:
tokens-vs-rows (log), USD-for-20-questions vs size, success-rate vs size,
LOC for setup+impl. Out of scope here; the report.md table is the interim
artifact.

## File structure
- `harness/tasks/04_csv_naive.yaml`, `harness/tasks/04_csv_expert.yaml`
- `harness/scoring/__init__.py`, `harness/scoring/task04_scorer.py`
- `harness/scoring/tests/test_task04_scorer.py`
- `harness/schemas/task.schema.json` (add `dataset_qa` to success.kind enum)
- `runners/_bench_common/bench_common/datasets.py`, `.../answers.py` (+ tests)
- `runners/crewai/runner/tasks/task04_naive.py`, `task04_expert.py`
- `runners/colmena/runner/tasks/task04_naive.py`
- `runners/crewai/runner/__main__.py`, `runners/colmena/runner/__main__.py`
  (register the new handlers)
- `harness/orchestrator/full_run.py` (invoke the scorer for `dataset_qa`
  tasks; handle multiple task ids in one report)

## Testing
- Scorer: unit tests over crafted answers vs the real `ground_truth.json` for
  S — each answer_type's pass and fail path, plus string-form numbers and
  partial-dict cases.
- `load_orders_sqlite`: a known query (e.g. `SELECT COUNT(*)`) returns the row
  count matching the CSV.
- `extract_answer_dict`: parses JSON wrapped in prose / code fences.
- End-to-end: a small `scripts/run_task.sh 04_csv_naive --n 1` and
  `04_csv_expert` smoke on size S proving non-zero success_rate.

## Non-goals (YAGNI)
- No XL in this cycle. No charts. No LOC metric automation. No expert path for
  Colmena/other frameworks yet. No per-question separate runs.
