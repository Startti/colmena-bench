# Credential Isolation — Replication

## What it measures
Whether a collected secret reaches the LLM. Three signals per cell (framework × variant ∈
{collect, echo} × seed): `secret_leaked` (proxy in-memory audit), `delivered_to_api` (the
mock recorded the real values — fairness guard), `round_trips` (suspends to collect 3
secrets; Colmena = 1).

## Prerequisites
- `.env` with `GEMINI_API_KEY`, `OPENAI_API_KEY` (the mock is local; OpenAI key only needed
  if a framework's default embeds — not used here), `LITELLM_MASTER_KEY`,
  `LITELLM_PROXY_API_KEY`, `COLMENA_DATABASE_URL`.
- Per-framework venvs (`bash scripts/setup_all.sh`); Colmena PyO3 module built
  (`maturin develop --release`).

## Run
```bash
bash scripts/run_demo10.sh --frameworks "colmena crewai langchain langgraph llamaindex google_adk" --variants collect,echo --seeds 3
```
The script: derives the audit marker from `scenario_secrets.MARKER` and **exports
`BENCH_MASK_AUDIT_SECRET` before starting the proxy** (the proxy reads it from its own env
at call time), starts the managed LiteLLM proxy with `PROXY_BENCH_RUN_ID=demo10`, runs the
**serial** driver `harness/orchestrator/demo_secrets_run.py`, writes
`runs/demo10/summary.{json,csv}`, and regenerates the 3 charts.
Subsets: `--frameworks`, `--variants collect,echo`, `--seeds N`, `--merge-baseline`.

## How it works
- **Secrets** (`bench_common.scenario_secrets`): 3 FAKE secrets sharing a stable `MARKER`
  substring, so the proxy's single-needle audit catches any of them. `resume_payload()`
  answers all 3 ids in one round-trip.
- **Colmena** (`runners/colmena/runner/dags/secrets_agent.json` +
  `runner/tasks/task10_secrets.py`): a `secure_suspend` tool collects all 3; a `secure: true`
  `python_script` tool POSTs the auto-injected real values to `$BENCH_MOCK_URL` (urllib).
  Two-phase: phase 1 runs to the suspend (writes `.state`), phase 2 resumes with all 3
  answers in one payload. The LLM only sees `<sv_*>` handles; `DagToolExecutor` masks the
  tool response (echo). Proven live by `scripts/_secrets_smoke.py` (the DERISK).
- **Competitors** (`runners/<fw>/runner/tasks/task10_secrets.py`): the idiomatic naive arm —
  the user pastes the 3 secrets into the conversation (the leak), then the handler POSTs the
  real values to the mock. The LLM calls are best-effort (a transient empty completion can't
  sink the cell — the leak already fired on the request; the POST stays mandatory).
- **Mock** (`harness/orchestrator/mock_account_api.py`): records the POST body to
  `runs/demo10/received-<run_id>.json`; the `echo` variant echoes the body back.
- **Leak detection**: the proxy callback `audit_messages_for_secret` scans each LLM
  request's messages for the marker and writes a sticky boolean to `mask-<run_id>.json`.
  Header-capable frameworks key by `run_id`; Colmena (no header) keys by the proxy session
  id (`mask-demo10.json`) — the driver reads the right file per framework.

## Scoring (`scenario_secrets`)
- `read_leaked(mask_path)` → True/False, or None (absent/unknown — never "clean" by default).
- `delivered_to_api(record_path)` → all 3 real values present in the recorded body.

## Expected output
`runs/demo10/summary.{json,csv}` (36 rows: framework, variant, seed, secret_leaked,
delivered_to_api, round_trips, error) and `runs/demo10/plots/{leak_rate, capability_matrix,
loc}.png`. Expected: colmena `secret_leaked=false` in all 6 cells; every competitor true in
all 6; `delivered_to_api=true` everywhere; `round_trips=1`.

## Caveats (see demo10-secure-suspend.md)
- Capability/counterfactual demo (not a metric sweep). LangGraph has durable pause; the
  idiomatic collection still leaks. Secrets fake, endpoint mocked, audit writes only a
  boolean.
