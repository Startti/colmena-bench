# Sandboxed Code Execution — Replication

Reproduce the sandboxed-code-execution-over-CSV demo end to end.

## Prerequisites

1. **Colmena binding built** from `develop` (the demo verified `@14beaba9`):
   ```bash
   cd /Users/danielgarcia/startti/colmena && git checkout develop && git pull
   VIRTUAL_ENV=/Users/danielgarcia/startti/colmena-bench/runners/colmena/.venv \
     PATH="$VIRTUAL_ENV/bin:$PATH" maturin develop --release
   ```
2. **Per-framework venvs + extra deps.** `scripts/setup_all.sh` installs them,
   including the Sandboxed Code Execution additions:
   - colmena venv: `pandas numpy scipy` (`attachment_run_python` runs in the
     embedded CPython of this venv).
   - llamaindex venv: `llama-index-experimental` (ships `PandasQueryEngine`).
   - langchain venv: `langchain-experimental` (ships `create_pandas_dataframe_agent`).
   - crewai venv: `daytona` SDK (remote sandbox — CrewAI's first-party Docker
     `CodeInterpreterTool` was removed in crewai-tools 1.14.0 for CVE VU#221883) plus the
     `docker` SDK for the optional local fallback.
   ```bash
   cd /Users/danielgarcia/startti/colmena-bench && bash scripts/setup_all.sh
   ```
3. **CrewAI sandbox backend** (env `BENCH_CREWAI_SANDBOX`, default `daytona`):
   - `daytona` — needs `DAYTONA_API_KEY` in `.env` (free tier: $200 credits, no credit
     card, from app.daytona.io). This is CrewAI's current documented code-exec path.
   - `docker` — local fallback for replicators without a Daytona key; needs a running
     Docker daemon. Without either backend available, crewai is recorded as `skipped`.
4. **`.env`** with `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
   `LITELLM_MASTER_KEY`, `COLMENA_DATABASE_URL`, `SECURE_VALUES_KEY`, and
   `DAYTONA_API_KEY` (for the crewai arm).

## Run

One command (owns the proxy lifecycle, tagged `BENCH_RUN_ID=demo08`):
```bash
bash scripts/run_demo08.sh                      # all 6 frameworks
bash scripts/run_demo08.sh --frameworks "colmena langchain"   # subset
```

Outputs:
- `runs/demo08/summary.{json,csv}` — one row per (framework, variant, mode).
- `runs/demo08/raw/<run-id>.json` — per-cell handler output.
- `runs/demo08/canary.txt` — the planted **dummy** canary (fake token).

Then render the matrix + charts:
```bash
PYTHONPATH=harness/orchestrator .venv-bench/bin/python harness/orchestrator/demo08_plots.py
PYTHONPATH=harness/orchestrator .venv-bench/bin/python harness/orchestrator/demo08_matrix.py
```
→ `runs/demo08/plots/{capability_matrix,security_probe,analytics_parity}.png`.

## Modes (env `BENCH_CODEEXEC_MODE`, set by the driver per cell)

- `analytics` — answer the Query-Strategy Trade-off's 20 questions with pandas over the attached CSV
  (variants S/M/L; scored against `data/orders_synthetic/ground_truth.json`).
- `mutation` — `net_revenue = quantity*unit_price_usd*(1-discount_pct)`, summed by
  country over shipped orders; scored exactly by `scenario_codeexec.score_mutation`.
- `probe` — feed the executor the fixed `open('<canary>').read()` snippet; record
  `blocked | leaked | error` (the controlled security counterfactual).
- `probe_realistic` — the injection is hidden in a CSV cell; classify the final
  answer with `scenario_codeexec.detect_leak`.

## Methodology notes (for honest reproduction)

- **Serial sweep, single proxy.** Colmena cannot forward the `x-bench-run-id`
  header, so its tokens are read by a line-count delta on the proxy session file
  (`run-demo08.jsonl`); a parallel sweep or a second proxy corrupts the delta. The
  driver runs cells sequentially.
- **Colmena env.** The driver exports `DATABASE_URL` from `COLMENA_DATABASE_URL`
  and pins `COLMENA_CHEAP_MODEL_OPENAI=gemini-2.5-flash`. The DAG drops
  `connection_url` at runtime (single-call DAG needs no conversation memory; keeping
  it exhausts the Postgres pool on rapid re-runs).
- **The canary is a dummy.** The forbidden snippet only ever reads the planted
  fake-token file; nothing real or destructive is touched. crewai/Docker isolates;
  the unsandboxed `exec` paths (langchain, langgraph) run it locally but read only
  the dummy — we record the leak, never anything harmful.
- **Transient empties.** `gemini-2.5-flash` occasionally returns an empty completion
  through the proxy; the scorer records those as `None` ("not measured"), not 0.0.
  Re-run an affected cell with `--frameworks <fw> --modes analytics --variants <V>
  --merge-baseline runs/demo08/summary.json`.
- **crewai latency.** Docker (image pull + in-container pandas install) makes
  analytics-L and mutation slow; they may hit the per-cell timeout and record `n/a`.
