# Task 4 — CSV analytical Q&A (naive vs expert strategy)

**A strategy demo, not a Colmena hero.** All 6 frameworks answer the same 20
analytical questions over a synthetic `orders` dataset (variants S=500, M=5k,
L=50k rows), two ways:

- **naive** — the whole CSV is pasted into the prompt; the model answers from context.
- **expert** — the model is given a `run_sql(query)` tool over a SQLite `orders`
  table and issues SQL; the CSV is **never** in context.

- **Reproduce:** `bash scripts/run_task4_all.sh` → `results/*-task04_csv_*/`, then
  `python harness/orchestrator/task4_aggregate.py` → `runs/task04/`
- **Model:** `gemini-2.5-flash` · tokens provider-authoritative (proxy spans) ·
  accuracy = fraction of 20 questions matching `data/orders_synthetic/ground_truth.json`

---

## 1. Headline results (mean across frameworks)

| Strategy | Variant | tok in | tok out | USD | accuracy |
|---|---|--:|--:|--:|--:|
| **expert** | S | ~51k | ~5k | $0.028 | **97–100%** |
| **expert** | M | ~51k | ~5k | $0.028 | **90–100%** |
| **expert** | L | ~52k | ~5k | $0.027 | **92–100%** |
| **naive** | S | 33.6k | 53k | $0.14 | **22–25%** |
| **naive** | M | 330k | 64k | $0.26 | **0–20%** |

**The lesson:** the *expert* (SQL-tool) strategy is **~5–9× cheaper AND ~4–7× more
accurate**, and its token cost is **independent of dataset size** (flat S→M→L). The
*naive* strategy grows linearly with the data and is far less accurate. This holds
for **every** framework — it's a property of the strategy, not the framework.

> Note on naive cost: the naive run is expensive on *both* sides — input grows with
> the CSV, **and** output explodes to 37–64k tokens (the model rambles over raw rows
> until it hits gemini's ~64k output cap). At $2.5/1M output that output dominates
> the USD. It is not a pricing bug; see the `tokens_out_mean` column.

Charts: `runs/task04/plots/tokens_asymptote.png`, `runs/task04/plots/accuracy.png`.

---

## 2. Fairness — what is identical across all 6 frameworks

This is a controlled comparison. Everything that could bias accuracy is shared:

- **Shared task prompt** (`harness/tasks/04_csv_expert.yaml` → `task_def['prompt']`):
  byte-identical for all 6 (the "return ONLY a JSON object Q01..Q20" instruction).
- **The 20 questions** (`data/orders_synthetic/questions_20.json`): identical.
- **The `run_sql` tool**: identical SQL execution and result format — header +
  `" | "`-joined rows, `"\n"`-joined lines, capped at 200 rows. (Colmena's tool is a
  fixed `python_script`; the 5 Python frameworks call `bench_common.load_orders_sqlite`'s
  `run_sql`. The output formatting is the same.)
- **Model + temperature**: `gemini-2.5-flash`, temp 0, through the same proxy.

The only per-framework difference is the idiomatic agent wiring (how each framework
loops a tool). Notably, **Colmena already has the most detailed framework-level system
message of the six** (LangChain/LangGraph have none) — so Colmena is, if anything,
mildly *advantaged* on prompting, not disadvantaged.

---

## 3. Clarification — why Colmena expert scores 88–92%, not ~100%

The 5 Python frameworks land at ~100% on the expert task; Colmena lands at **88–92%**.
We investigated this thoroughly. **It is not a bug, not the bench handler, and not a
prompt gap** — it is a *characterized, deliberate Colmena behavior*.

**What we measured** (instrumented run logging every SQL query + result):
1. Colmena runs **all 20 correct queries** (incl. the per-month `GROUP BY` for Q16 and
   per-country `GROUP BY` for Q15).
2. The tool **returns the full, correct rows** every time.
3. Yet the final answer is wrong on exactly **two** questions — **Q16** (orders per
   month, 24 values) and **Q15** (top category per country, 8 values) — the only two
   whose answer is a *large structured object*. All 18 scalar questions pass.
4. The failure pattern is **confabulation**: the first ~10 entries are copied exactly,
   then the rest collapse to a plausible constant (Q16 → a round "20"; Q15 →
   "electronics" for every country).

**Root cause — Colmena's rolling-summary context compaction** (engine source
`colmena/src/libs/colmena/src/llm/application/agent_service.rs`):
- Before each LLM call, `compact_history_to_summary()` keeps verbatim only the
  **first 2** and **last 5** messages (`COMPACT_SUMMARY_KEEP_FIRST_MSGS=2`,
  `COMPACT_SUMMARY_KEEP_RECENT_MSGS=5`).
- Every middle message is collapsed to **one line capped at 180 chars**
  (`COMPACT_SUMMARY_LINE_MAX_CHARS=180`, `summary_line_for_message`). A tool result
  becomes `[T15] TOOL(run_sql) → <first 180 chars>…`.
- In the expert run (~20 tool calls ≈ 40 messages), Q16's monthly table (query #15/20)
  and Q15's per-country table (#14) fall **outside the recent-5 window** → squashed to
  ~180 chars ≈ the first ~10 entries. The final generation literally only sees the head
  of those tables → copies them and **fabricates the tail**. It is systematic (Q16
  fails 9/9) because Q16 always lands in the same position.

The full content **is** persisted verbatim (Postgres), and the agent can call
`recall_history(turn=N)` to pull any turn back — but the model doesn't know it lost
precision (the truncated line looks plausible), so it doesn't.

---

## 4. Why this clarification matters for the pitch

**This is the same mechanism that wins Demo 05.** Colmena's flat-token "context tax"
advantage (~12× cheaper on long conversations) comes from exactly this aggressive
context compaction. Task 4 expert exposes the *other side of the same coin*:

| | Demo 05 (Colmena wins) | Task 4 expert (Colmena 88–92%) |
|---|---|---|
| Mechanism | rolling summary + ephemeral attachments | **the same rolling summary** |
| Effect | flat tokens, ~12× cheaper | large mid-conversation tool tables get truncated |

So the honest one-liner is: **Colmena defaults to context economy.** On a
transcription-heavy workload that re-reads large mid-conversation tool dumps, that
default costs a few points of accuracy; the same default is what makes long agent
conversations dramatically cheaper. It is tunable (`KEEP_RECENT` / `LINE_MAX_CHARS`)
and recoverable (`recall_history`), but out of the box it is 88–92% here vs ~100% for
frameworks that re-send full history (and pay for it in tokens elsewhere).

**Do not "fix" this with a Colmena-only prompt hint** — it would be unfair (the others
don't get it) and wouldn't address the cause (the model already has the richest prompt
and ran the right queries). The 88–92% is a real, fairly-measured Colmena
characteristic.

---

## 5. Files

- Task YAMLs: `harness/tasks/04_csv_{naive,expert}.yaml`
- Dataset + ground truth: `data/orders_synthetic/`
- Handlers: `runners/<framework>/runner/tasks/task04_{naive,expert}.py`
- Aggregator + charts: `harness/orchestrator/task4_aggregate.py`
- Summary data: `runs/task04/task4_summary.{json,csv}`
- Memory note: `colmena-rolling-summary-tradeoff` (in the project memory index)
