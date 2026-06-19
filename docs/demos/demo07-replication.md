# Demo #7 — Replication & Analysis Guide

How to reproduce the many-tools lazy-loading demo from scratch, where the data
lives, and how the tokens are measured. Pair with
[demo07-many-tools.md](demo07-many-tools.md) (results & pitch) and
[../TECHNICAL.md](../TECHNICAL.md) (methodology).

---

## 0. Prerequisites (once)

1. **Clone both repos as siblings:**
   ```
   <root>/colmena-bench     # this repo
   <root>/colmena           # the Colmena engine (Rust), branch `develop`
   ```
2. **Build the Colmena Python binding from `develop`** into the bench's Colmena
   venv (needed for `run_dag` and the lazy-tool-loading node flag):
   ```bash
   cd <root>/colmena && git checkout develop && git pull
   VIRTUAL_ENV=<root>/colmena-bench/runners/colmena/.venv \
     PATH="$VIRTUAL_ENV/bin:$PATH" maturin develop --release
   ```
   (Python 3.11 venv; run from the colmena REPO ROOT so `pyproject.toml
   [tool.maturin]` applies.)
3. **Per-framework venvs + proxy venv:**
   ```bash
   cd <root>/colmena-bench && ./scripts/setup_all.sh
   ```
4. **`.env`** (repo root) must define:
   - `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` (real provider keys)
   - `LITELLM_MASTER_KEY` and `LITELLM_PROXY_API_KEY` (= master key)
   - `OPENAI_BASE_URL=http://127.0.0.1:4000/v1`
   - `COLMENA_DATABASE_URL=postgresql://…` (Postgres for the DAG engine — NOT named
     `DATABASE_URL`, or LiteLLM auto-loads it and crashes; the Colmena handler
     copies `COLMENA_DATABASE_URL` → `DATABASE_URL` at `run_dag` time)
   - `SECURE_VALUES_KEY=<≥32 chars>` (pgcrypto key for the secure-value backend the
     engine initializes)
   - Default model is `gemini-2.5-flash`.

Everything routes through the local LiteLLM proxy, which is the
**provider-authoritative source of truth** for tokens. Nothing trusts a framework's
self-report.

---

## 1. Run the experiment

`scripts/run_demo07.sh` owns the proxy lifecycle (it starts the LiteLLM proxy with
`BENCH_RUN_ID=demo07`, waits for readiness, runs the sweep driver, then kills the
proxy on exit). All CLI args pass straight through to the driver.

**Full grid** (counts `5,10,25,50,100,200` × difficulties `easy,medium,hard`,
default 5 trials) — this is the long one:
```bash
bash scripts/run_demo07.sh
```

**Small grid** (fast — what the current `summary.json` was produced from):
```bash
bash scripts/run_demo07.sh --counts 5,50,200 --difficulties hard --trials 2
```

Outputs land in `runs/demo07/summary.{json,csv}` — one row per
`(config, count, difficulty)`, means over trials.

### Multi-turn SESSION sweep (v2 — the primary result)

The session driver replays a fixed ~30-tool toolset over a **10-turn conversation**
for each `(config, seed)`, sweeping **5 seeds (0–4)**, and reports **cumulative
input tokens per turn** + per-turn selection accuracy. It does NOT own the proxy —
start the proxy first (the same way `run_demo07.sh` does), source `.env` so the
Colmena engine gets `COLMENA_DATABASE_URL` + `SECURE_VALUES_KEY`, then:

```bash
# 1. proxy (BENCH_RUN_ID=demo07 so its session span file is run-demo07.jsonl)
pkill -f "litellm --config"; sleep 1
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=demo07 \
  nohup bash proxy/start_proxy.sh >/tmp/d7_proxy.log 2>&1 &
# wait for http://127.0.0.1:4000/health/liveliness == 200

# 2. env + driver (full 7-config × 5-seed sweep)
set -a; source .env; set +a
PROXY_BENCH_RUN_ID=demo07 \
  .venv-bench/bin/python harness/orchestrator/demo_tools_session_run.py

# small validation slice instead of the full sweep:
#   ... demo_tools_session_run.py --configs colmena-lazy,langchain --seeds 0
```

Outputs land in `runs/demo07/session_summary.{json,csv}` — one row per
`(config, turn)`, means over seeds: `cum_tokens_mean`, `per_turn_tokens_mean`,
`selection_acc`. Per-run detail is in `runs/demo07/session_records.json`.

Render the session charts:
```bash
.venv-bench/bin/python harness/orchestrator/demo07_session_plots.py
```
Writes to `runs/demo07/plots/`:
- `session_cum_tokens_vs_turn.png` — HERO: cumulative input tokens vs turn, one line
  per config (colmena-lazy lowest/flattest).
- `session_selection_vs_turn.png` — selection accuracy vs turn.
- `session_cum_tokens_at_turn10_bar.png` — cumulative tokens at the last turn per
  config, with the colmena-lazy ratio annotated.

**Per-turn token accounting.** Each session handler emits
`extras.turn_boundaries` (11 ISO timestamps for 10 turns — one before turn 0 + one
after each turn). The driver buckets proxy spans into turns by wall-clock with
`harness/orchestrator/demo05_buckets.bucket_spans_by_turn`, then takes the
cumulative input-token sum per turn. Tool calls are bucketed the same way by their
logged `ts` and scored with `scenario_tools.score_turn`.

**Colmena token delta (same trick, applied per run).** Colmena's engine does not
forward `x-bench-run-id`, so all its spans land in the single session file
`proxy/spans/run-demo07.jsonl`. The driver records that file's line count *before*
each Colmena subprocess and loads only the lines appended *after* as that run's
spans (`line_count` + `load_spans_from_offset`). Competitors forward the header, so
their spans are read whole from `proxy/spans/run-<run_id>.jsonl`. This requires a
**serial sweep + a single proxy** — a parallel run or a second proxy corrupts the
delta. In the seed-0 validation this delta produced **nonzero** Colmena tokens
(≈41.7k cumulative at turn 9), confirming the accounting works.

**503 / overloaded retry.** `gemini-2.5-flash` occasionally returns a transient
5xx / "overloaded" / "unavailable". Each competitor session handler wraps its
bound-LLM invoke in a 3× retry with backoff (`_invoke_with_retry`); a turn that
still fails is recorded as an error string and does not sink the run (each turn is
isolated in a `try/finally` that always appends a turn boundary). If a whole run
hard-errors (e.g. Colmena missing `COLMENA_DATABASE_URL`), the driver skips it in
aggregation and writes its stderr to `runs/demo07/session_raw/<run_id>.stderr`.

### Render the charts
```bash
.venv-bench/bin/python harness/orchestrator/demo07_plots.py
```
Writes to `runs/demo07/plots/`:
- `tokens_vs_tools_<diff>.png` — HERO: input tokens (log y) vs #tools, one line per
  config, for each difficulty present.
- `accuracy_vs_tools_<diff>.png` — `answer_acc` vs #tools, for each difficulty.
- `tokens_at_200_bar.png` — bar of `tokens_in_mean` per config at N=200, hard, with
  the ratio vs the cheapest competitor annotated.

The plotter renders whatever subset of the grid is in `summary.json` and skips a
facet gracefully if it has no rows — so it works on the small grid (just the `hard`
facet + the bar) and again on the full grid after the long sweep. Re-run it after
the full sweep to pick up the `easy` / `medium` facets and the intermediate tool
counts.

---

## 2. Environment the driver sets per cell

The driver (`harness/orchestrator/demo_tools_run.py`, `_env_for`) writes a stable
toolset for the cell and hands each runner subprocess:

| env var | meaning |
|---|---|
| `BENCH_TOOLSET_PATH` | path to the generated toolset JSON for this cell (name+summary catalog, full param schemas, the question, and the needle answer). Identical bytes for all 7 configs at a given trial. |
| `BENCH_TOOLCALL_LOG` | path the runner appends each tool call to, for selection/arg scoring. |
| `BENCH_COLMENA_LAZY` | `1` (colmena-lazy) or `0` (colmena-eager) — toggles the engine's `lazy_tool_loading` node flag. **Colmena only**; the 5 competitors have no such toggle. |
| `BENCH_RUN_ID` | per-cell run id (used by the header-capable competitors). |
| `LITELLM_PROXY_BASE_URL`, `LITELLM_PROXY_API_KEY` | route the runner's LLM calls through the proxy. |

The proxy's own `BENCH_RUN_ID=demo07` is set by `run_demo07.sh`; the driver reads it
back via `PROXY_BENCH_RUN_ID=demo07` to know which session span file holds Colmena's
tokens.

---

## 3. The token-measurement note (important — Colmena vs competitors)

Tokens are summed from the proxy spans, but the two engine families land in
*different* span files:

- **Competitors** are header-capable: their LLM calls forward `x-bench-run-id`, so
  their spans go to `proxy/spans/run-<run_id>.jsonl` (the per-cell run id). Their
  cell tokens are the **full sum** over that file.
- **Colmena's engine** does NOT forward the header, so *all* of its spans land in
  the single session file `proxy/spans/run-<PROXY_BENCH_RUN_ID>.jsonl`
  (`run-demo07.jsonl`), mixed across cells. Because the driver runs cells
  **sequentially**, Colmena tokens are measured by **delta**: record the session
  file's line count *before* the subprocess, then sum `tokens_input` over only the
  lines appended *after* (`line_count` + `sum_tokens_from_offset` in the driver).

This is why the demo **must not be run with a parallel sweep** and why you must not
start a second proxy mid-run: the delta accounting assumes one proxy and one
in-flight Colmena cell at a time.

---

## 4. Files

- Sweep driver: `harness/orchestrator/demo_tools_run.py`
- Driver script (proxy lifecycle): `scripts/run_demo07.sh`
- Task YAML: `harness/tasks/07_tools.yaml`
- Toolset generator + scoring: `runners/_bench_common/bench_common/scenario_tools.py`
- Handlers: `runners/<framework>/runner/tasks/task07_tools.py`
- Charts: `harness/orchestrator/demo07_plots.py`
- Data + plots: `runs/demo07/summary.{json,csv}`, `runs/demo07/plots/`
