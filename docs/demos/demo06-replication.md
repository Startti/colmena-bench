# Demo #4 — Replication & Analysis Guide

How to reproduce the production refund-agent demo from scratch, where the data
lives, and how to read the masking audit. Pair with
[demo06-refund-agent.md](demo06-refund-agent.md) (results & pitch) and
[../TECHNICAL.md](../TECHNICAL.md) (methodology).

---

## 0. Prerequisites (once)

1. **Clone both repos as siblings:**
   ```
   <root>/colmena-bench     # this repo
   <root>/colmena           # the Colmena engine (Rust), branch `develop`
   ```
2. **Build the Colmena Python binding from `develop`** into the bench's Colmena
   venv (needed for `run_dag`, the secure-value backend, and the suspend/resume
   primitives this demo uses):
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
     `DATABASE_URL`, or LiteLLM auto-loads it and crashes; the Colmena refund DAG
     copies `COLMENA_DATABASE_URL` → `DATABASE_URL` at `run_dag` time)
   - `SECURE_VALUES_KEY=<≥32 chars>` (pgcrypto key for the secure-value backend —
     required: `secure: true` masking and `secure_suspend` depend on it)
   - Default model is `gemini-2.5-flash`.

Everything routes through the local LiteLLM proxy, which is the
**provider-authoritative source of truth** — for both tokens and, here, the
**masking audit**. Nothing trusts a framework's self-report.

---

## 1. Run the experiment

**One full pass (all 6 frameworks)** — the script owns the proxy lifecycle:
```bash
bash scripts/run_demo06.sh
# → runs/demo06/summary.{json,csv}
```

`run_demo06.sh` sources `.env`, starts the LiteLLM proxy with the masking-audit
secret **armed** (`BENCH_MASK_AUDIT_SECRET=sk-live-REFUND-SECRET-abc123`, matching
`scenario_refund.SECRET`) under `BENCH_RUN_ID=demo06`, waits for readiness, runs the
two-process driver (`harness/orchestrator/demo_refund_run.py`) across all six
frameworks (colmena, crewai, langchain, llamaindex, **langgraph**, **google_adk**),
then kills the proxy on exit.

> **LangGraph dependency.** The langgraph runner's durable cross-process HITL uses a
> file-backed `SqliteSaver` checkpointer, which needs `langgraph-checkpoint-sqlite`.
> It is declared in `runners/langgraph/pyproject.toml` and installed by
> `scripts/setup_all.sh` — no extra step if you ran setup.

Subset a run with `--frameworks`:
```bash
bash scripts/run_demo06.sh --frameworks "colmena crewai"
```

**Render the charts** from the saved summary (no LLM calls, no proxy needed):
```bash
.venv-bench/bin/python harness/orchestrator/demo06_plots.py
# → runs/demo06/plots/{capability_matrix,masking_guarantee,loc_code_vs_config}.png
```

**Regenerate the capability-matrix markdown table** (the one embedded in the pitch):
```bash
.venv-bench/bin/python -c \
  "import sys; sys.path.insert(0,'harness/orchestrator'); import demo06_matrix; print(demo06_matrix.render_markdown())"
```

---

## 2. The two-process HITL (durable cross-process suspend)

The point of this demo's HITL is that it is **durable across processes**, not a
blocking in-process prompt. The driver (`demo_refund_run.py`) runs each framework
in two phases:

- **Phase 1** runs draft → critic-retry → confirm (with the masked payment tool),
  then **suspends** for human approval and **persists state**, then the process
  exits.
  - Colmena: the engine's `suspend` node persists the run state to Postgres and
    returns a suspend token.
  - Competitors: the handler writes a `.state` file (`<output>.state`) and returns
    `{"suspended": True}`.
- **Phase 2** is a **fresh process** that rehydrates the persisted state and
  finishes (resume the suspended Colmena run / load the `.state` file), feeding the
  canonical human answer (`scenario_refund.CANONICAL_HUMAN_ANSWER`) and routing the
  decision to approve / reject / escalate.

Because phase 2 is a separate process that only has the persisted state, this
exercises true cross-process durability — no competitor offers it natively (see the
pitch doc §4).

---

## 3. The masking audit — `BENCH_MASK_AUDIT_SECRET` and the spans

Masking is **verified at the proxy**, not by trusting the frameworks.

- `run_demo06.sh` starts the proxy with `BENCH_MASK_AUDIT_SECRET` set to the secret
  value the payment tool returns (`scenario_refund.SECRET` =
  `sk-live-REFUND-SECRET-abc123`).
- The proxy callback **scans every outbound request body** (the messages sent to
  the provider) for that secret substring. If it ever appears in the clear, the
  audit records a leak.
- The result is written to `proxy/spans/mask-<run_id>.json`. For the orchestrated
  run that is **`proxy/spans/mask-demo06.json`**:
  ```json
  {"secret_leaked": false}
  ```
  `secret_leaked: false` means the secret never reached the provider in the clear —
  the masking held. A `true` would mean a leak.

**Reading per-framework / counterfactual audits.** Individual runs write their own
`mask-<run_id>.json` (e.g. `mask-refund-crewai.json`). The **naive counterfactual**
— the variant that omits the manual scrub — writes a span with
`{"secret_leaked": true}`, which is how the leak claim in the pitch is proven. To
inspect any audit:
```bash
cat proxy/spans/mask-<run_id>.json
```

The per-framework pass/leak status is also rolled into `runs/demo06/summary.json`
(`secret_leaked` / `masking_ok` per framework).

---

## 4. The saved data layer

| Path | Contents |
|---|---|
| `runs/demo06/summary.json` | Per framework: `code_loc`, `config_loc`, `ok`, the refund `answer` (decision/amount/justification), `retries`, `secret_leaked`, `router_branch`/`final_intent`, `hitl_ok`, `critic_ok`, `masking_ok`, `all_ok` |
| `runs/demo06/summary.csv` | Same, one row per framework (Excel/Sheets ready) |
| `runs/demo06/plots/*.png` | `capability_matrix.png` (centerpiece), `masking_guarantee.png` (hero), `loc_code_vs_config.png` (honest LOC) |
| `proxy/spans/mask-<run_id>.json` | The masking audit per run; `mask-demo06.json` is the orchestrated run |
| `runs/demo06/raw/<framework>/` | Raw runner stdout/scratch (git-ignored) |

Write your own analysis on top of `summary.json`:
```python
import json
for r in json.load(open("runs/demo06/summary.json")):
    print(r["framework"], r["all_ok"], r["secret_leaked"], r["code_loc"], r["config_loc"])
```

---

## 5. Reproducibility notes

- **Determinism:** model `temperature=0`; the customer message, policy text,
  requested amount, secret, and payment-tool result shape are fixed in
  `runners/_bench_common/bench_common/scenario_refund.py`. The 250 USD case deterministically forces the
  critic path (auto-approve > 100 is a policy violation) and the `escalate` outcome.
- **Engine dependency:** the Colmena run requires the `develop` binding (secure
  values + suspend/resume). `SECURE_VALUES_KEY` and `COLMENA_DATABASE_URL` must be
  set or the `secure: true` masking and `secure_suspend` will fail.
- **Masking scope (honest):** the engine re-masks whole `secure: true` tool results
  only; a secure handle routed into a plain `llm_call` prompt edge is decrypted and
  would leak (see pitch doc §3). The DAG deliberately models the payment as a
  `secure: true` *tool* so masking applies.
- **Scope:** all 6 frameworks now run — colmena + crewai + langchain + llamaindex +
  langgraph + google_adk. Round-2 finding: LangGraph is the honest near-peer (native
  graph + durable cross-process HITL via `interrupt()` + file `SqliteSaver` + graph-loop
  critic retry); the differentiation narrows to **masking**, the one primitive no
  Python framework offers natively (see the pitch doc §3 and the round-2 subsection).
</content>
