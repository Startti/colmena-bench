# Demo 05 — Replication & Analysis Guide

How to reproduce the "context tax" experiment from scratch, where the data lives,
and how to run analyses (plots, LLM-judge, your own) **on the saved data without
re-running the agents**. Pair with [demo05-context-tax.md](demo05-context-tax.md)
(results) and [../TECHNICAL.md](../TECHNICAL.md) (methodology).

---

## 0. Prerequisites (once)

1. **Clone both repos as siblings:**
   ```
   <root>/colmena-bench     # this repo
   <root>/colmena           # the Colmena engine (Rust), branch `develop`
   ```
2. **Build the Colmena Python binding from `develop`** (has the merged attachment
   fixes #103/#104) into the bench's Colmena venv:
   ```bash
   cd <root>/colmena && git checkout develop && git pull
   VIRTUAL_ENV=<root>/colmena-bench/runners/colmena/.venv \
     PATH="$VIRTUAL_ENV/bin:$PATH" maturin develop --release
   ```
   (Python 3.11 venv; pyo3 0.21 supports ≤3.12. Run from the colmena REPO ROOT so
   `pyproject.toml [tool.maturin]` applies.)
3. **Per-framework venvs + proxy venv:**
   ```bash
   cd <root>/colmena-bench && ./scripts/setup_all.sh
   ```
4. **`.env`** (repo root) must define:
   - `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` (real provider keys)
   - `LITELLM_MASTER_KEY` and `LITELLM_PROXY_API_KEY` (= master key)
   - `OPENAI_BASE_URL=http://127.0.0.1:4000/v1`
   - `COLMENA_DATABASE_URL=postgresql://…` (Postgres for the DAG engine — NOT named
     `DATABASE_URL`, or LiteLLM auto-loads it and crashes; see TECHNICAL.md §4)
   - `SECURE_VALUES_KEY=<≥32 chars>` (pgcrypto key for the secure-value backend)
   - Default model is `gemini-2.5-flash` (uses your Gemini credits).

Everything routes through the local LiteLLM proxy, which is the **provider-authoritative
token source of truth**. Nothing trusts a framework's self-reported usage.

---

## 1. Run the experiment

**One full pass (all 6 frameworks, ~5 min)** — handles proxy lifecycle internally:
```bash
./scripts/run_demo05.sh
# → runs/demo05/report/{report.md, chart_data.json}
```

**N passes for mean ± std (default N=12, ~1 h)** — each pass gets its own proxy
session so per-pass Colmena spans never collide:
```bash
bash scripts/run_demo05_n.sh 12
# → runs/demo05/n12/run_<i>/report/chart_data.json   (one per pass)
```

---

## 2. The saved data layer (reuse it — don't re-run)

Every run persists **all metrics + the raw answers** as JSON/CSV, so analyses run
on top of it offline:

| Path | Contents |
|---|---|
| `runs/demo05/n12/run_*/report/chart_data.json` | Per pass, per framework: tokens (in/out/cached, per-turn + total), provider+wall latency, TTFT, LLM call counts, peak RAM, CPU (user/sys), USD, LOC, `quality_ok`, **and the 10 raw answers** |
| `runs/demo05/report/agg_n12.json` | Aggregate: mean/std of every metric, per-turn means |
| `runs/demo05/report/agg_n12_summary.csv` | One row per framework — all metrics (Excel/Sheets ready) |
| `runs/demo05/report/agg_n12_per_turn.csv` | Per framework × turn: cumulative + per-turn tokens, latency, calls |
| `runs/demo05/report/judge_n12.json` / `_summary.csv` | LLM-judge quality scores (0–1) |
| `runs/demo05/report/judge_cache.json` | Judge cache keyed by answer hash (re-runs are incremental) |
| `runs/demo05/report/plots/*.png` | The 14 charts |

> Note: `runs/**/raw/` (raw runner stdout + proxy span files) is git-ignored
> scratch; the committed `chart_data.json` already holds the distilled per-pass data.

---

## 3. Analyses on top of the saved data

**Aggregate** N passes → JSON + CSV (no LLM calls):
```bash
python harness/orchestrator/demo05_aggregate_n.py --base runs/demo05/n12
```

**Render all 14 charts** from the aggregate (no LLM calls):
```bash
python harness/orchestrator/demo05_plots.py        # reads agg_n*.json (+ judge if present)
```

**LLM-judge over the SAVED answers** (no agent re-run; needs the proxy up for the
grader calls; incremental via the cache):
```bash
# proxy up:
set -a; source .env; set +a
export LITELLM_PROXY_API_KEY="$LITELLM_MASTER_KEY"
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=judge ./proxy/start_proxy.sh &
# judge:
python harness/orchestrator/demo05_judge.py                       # doc turns
python harness/orchestrator/demo05_judge.py --turn-types doc follow_up   # more coverage
python harness/orchestrator/demo05_judge.py --max-passes 3        # limit cost
```

**Write your own analysis:** load `agg_n12.json` (or the per-pass `chart_data.json`)
— every metric and every raw answer is there. Example:
```python
import json
agg = json.load(open("runs/demo05/report/agg_n12.json"))
for r in agg["frameworks"]:
    print(r["framework"], r["total_mean"], r["ram_peak_mb_mean"])
```

---

## 4. The 14 charts (`runs/demo05/report/plots/`)

| # | File | Shows |
|---|---|---|
| 1 | `1_bar_total_tokens` | total input tokens, mean ± std |
| 2 | `2_line_cumulative` | cumulative tokens/turn (± std band) — the asymptote |
| 3 | `3_line_per_turn` | per-turn input cost |
| 4 | `4_bar_usd` | USD/conversation + at-scale $/yr projection |
| 5 | `5_multiplier_curve` | competitor÷Colmena ratio per turn (compounding) |
| 6 | `6_quadrant` | cost × maintained code (LOC) |
| 7 | `7_loc_bar` | imperative handler LOC (DAG noted separately) |
| 8 | `8_stacked_composition` | estimated token composition (illustrative) |
| 9 | `9_bar_latency` | total provider latency |
| 10 | `10_line_calls` | LLM calls per turn |
| 11 | `11_bar_ram` | peak RSS (Colmena lowest) |
| 12 | `12_bar_cpu` | CPU seconds |
| 13 | `13_bar_quality` | LLM-judged answer quality (0–1) |
| 14 | `14_quadrant_cost_quality` | cost × quality (Colmena: cheap + high quality) |

Distinct color per competitor; Colmena is the bold green hero.

---

## 5. What each metric means + honest scope

- **Tokens / USD** — provider-authoritative (captured at the proxy). The headline.
- **LOC** — imperative handler `.py` only; the Colmena agent is a declarative DAG
  (`runners/colmena/dags/demo05_turn.json`, ~71 lines, counted as config not code).
- **RAM (peak RSS)** — sampled during the run (true peak) of the runner process;
  excludes the shared proxy; for Colmena includes its in-process Rust engine.
  **Colmena wins (≈49 MB vs 96–279).**
- **CPU (user+sys)** — `getrusage(RUSAGE_SELF)`; Colmena is mid-pack (honest, not a win).
- **Wall-clock latency** — captured but **not featured**: Colmena rebuilds the engine
  per `run_dag` call here (a bench artifact; production uses a persistent
  `serve_dag`). Provider-side latency is lowest for Colmena.
- **Quality** — `quality_ok` is a cheap substring guardrail (doc facts present);
  the **LLM-judge** (`judge_n12.json`) is the graded 0–1 score. All 6 ≈ 0.97–1.0:
  Colmena's token savings cost no measurable quality.

---

## 6. Reproducibility notes

- **Determinism:** model `temperature=0`; the report, the 10-turn script, and the
  chart tool's base64 payload are fixed (`bench_common/scenario05.py`). Competitor
  token totals are near-deterministic (tight std). Colmena's total varies (~37–66k)
  because the model decides per turn whether to re-read the doc via `load_attachment`
  — hence N≥12 + error bars.
- **Engine dependency:** results require the colmena `develop` binding (attachment
  fixes #103/#104). With an older binding, attachment turns fail.
- **Fairness:** competitors run their default idiomatic memory; no hand-tuning.
  Colmena's extra `load_attachment` round-trips count against it.
