# colmena-bench — Technical Documentation

**Purpose.** A reproducible, *demonstrably fair* benchmark that compares **Colmena**
(a Rust agent framework) against five Python frameworks — **CrewAI, LangChain,
LangGraph, LlamaIndex, Google ADK** — to show where Colmena genuinely wins. A
benchmark only sells if it measures real differences under identical conditions;
this doc records how that fairness is engineered.

> Companion docs: [demos/demo05-context-tax.md](demos/demo05-context-tax.md)
> (the hero demo), [SELLING_COLMENA.md](SELLING_COLMENA.md) (the pitch),
> [superpowers/specs/2026-06-11-benchmark-strategy-colmena-differentiators.md](superpowers/specs/2026-06-11-benchmark-strategy-colmena-differentiators.md)
> (strategy).

---

## 1. Design principles

1. **Provider-authoritative tokens.** Token/cost numbers are NEVER taken from a
   framework's self-report. Every LLM call is routed through a local **LiteLLM
   proxy** that records the provider's own usage per call. The proxy is the single
   source of truth.
2. **Identical conditions.** Same model (`gemini-2.5-flash`), same proxy, same
   task definitions, same inputs (documents, tool payloads, conversation scripts)
   across all six frameworks. The only variable is the framework.
3. **Idiomatic, un-handicapped competitors.** Each competitor uses its own
   default/idiomatic API and memory. No hand-tuning against them, no strawman.
4. **Pinned versions.** Each runner has its own venv with pinned dependencies.
5. **Adversarial review.** Hero results are reviewed by an independent skeptic
   pass before they are published (see the demo doc).

---

## 2. Repository layout

```
colmena-bench/
├── proxy/                      # LiteLLM proxy = token source of truth
│   ├── litellm_config.yaml     # model aliases, master_key auth, spans callback
│   ├── spans_callback.py       # writes one span per LLM call → proxy/spans/
│   ├── start_proxy.sh          # proxy lifecycle (see §4)
│   └── spans/run-<id>.jsonl    # per-run captured spans (tokens, latency, ttft)
├── runners/
│   ├── _bench_common/          # shared, framework-agnostic runner core
│   │   └── bench_common/       # core.py, datasets.py, answers.py, scenario05.py
│   └── <framework>/            # one dir per framework
│       ├── .venv/              # pinned per-framework venv
│       └── runner/
│           ├── __main__.py     # registers task handlers
│           ├── llm.py          # builds the framework's LLM, routed at the proxy
│           └── tasks/          # task01.py, task04_*.py, task05.py
├── harness/
│   ├── tasks/                  # task definitions (YAML)
│   ├── orchestrator/           # full_run.py (single-shot) + demo05_* (multi-turn)
│   ├── scoring/                # task04_scorer.py (dataset QA)
│   └── pricing_table.json      # dated price snapshot for USD
├── data/orders_synthetic/      # Task 4 dataset + ground truth
├── runs/                       # run outputs + reports
└── scripts/                    # setup_all.sh, run_task.sh, run_demo05.sh, smokes
```

---

## 3. The runner contract

Every runner is a thin adapter over a shared core (`bench_common/core.py`). The
core parses args, dispatches to a per-task handler, times it, and writes a uniform
JSON output. A handler is:

```python
def run(task_def, llm, args) -> (answer, usage)            # 2-tuple, or
def run(task_def, llm, args) -> (answer, usage, extras)    # 3-tuple (multi-turn)
```

- `answer` — the task result (string, dict, or per-turn list).
- `usage` — `{"input","output","cached","tool_calls"}`; left at 0 by handlers —
  **the orchestrator overwrites tokens from the proxy spans** (principle #1).
- `extras` — optional; multi-turn handlers return `turn_boundaries` (ISO-8601
  timestamps, one before turn 0 and one after each turn) so the orchestrator can
  attribute spans to turns (see §5).

The framework's LLM object is built in `runner/llm.py` and is always pointed at
the proxy. For the five Python frameworks this uses the `openai/<alias>` model
prefix + `base_url` + an `x-bench-run-id` header so the proxy can route that run's
spans to `run-<run_id>.jsonl`.

---

## 4. The proxy (token source of truth)

`proxy/start_proxy.sh` launches LiteLLM with the spans callback. Auth is DB-free
(`master_key`); spans are written to JSONL files, one line per LLM call:

```json
{"span_id","run_id","ts_start","ts_end","latency_ms","model_alias",
 "provider_model","tokens_input","tokens_output","tokens_cached","ttft_ms","ok"}
```

**Footgun fixed:** the proxy must NOT see a `DATABASE_URL` — LiteLLM auto-detects
it and tries to start a Prisma client (not installed for master_key auth) and
refuses to boot. The Colmena Postgres URL is therefore stored as
`COLMENA_DATABASE_URL` in `.env`; only the Colmena DAG path re-exports it as
`DATABASE_URL`. `start_proxy.sh` also `unset`s `DATABASE_URL` defensively.

Run it:
```bash
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=<id> ./proxy/start_proxy.sh
```

---

## 5. Span correlation (how tokens map to runs and turns)

- **Header-capable runners** (the 5 Python frameworks): each call carries
  `x-bench-run-id: <run_id>`, so the proxy writes `run-<run_id>.jsonl`.
- **Colmena**: its OpenAI adapter cannot forward a custom header, so its spans
  land in the proxy's session file `run-<BENCH_RUN_ID>.jsonl`. The orchestrator
  starts the proxy with `BENCH_RUN_ID == Colmena's run_id` so the file name lines
  up.
- **Per-turn attribution** (multi-turn demos): the runner emits
  `extras.turn_boundaries`; `harness/orchestrator/demo05_buckets.py` buckets each
  span into a turn by comparing its `ts_start` to the boundaries. This is
  framework-agnostic and counts *all* of a framework's calls — including
  Colmena's extra `load_attachment` round-trips, which therefore count *against*
  Colmena, not for it.

---

## 6. Colmena integration

Colmena is a Rust workspace; the bench drives it via the PyO3 Python binding
(`pip` package `colmena-ai`, import `colmena`), built with
`maturin develop --release` **from the colmena repo root** (so the root
`pyproject.toml [tool.maturin]` applies: `features=["pyo3/extension-module",
"python"]`, `module-name="colmena"`, `python-source="stubs"`). Build into the
bench's Colmena venv by setting `VIRTUAL_ENV` to `runners/colmena/.venv`
(Python 3.11; pyo3 0.21 supports ≤3.12).

Two execution surfaces are used:
- `ColmenaLlm.call(...)` — single-shot (Task 1, Task 4-naive).
- `colmena.run_dag(graph, resume_id, resume_answer, inject_payload,
  include_extra_info, agent_session_id)` — executes a JSON DAG (Demo 05). Needs
  Postgres (`DATABASE_URL`) and `SECURE_VALUES_KEY` (≥32 chars).

**Engine fixes landed for this bench** (merged to colmena `develop`):
- **#103** — inline *text* attachments skip the provider Files API; bytes are
  persisted to storage and served via `load_attachment`. (The LiteLLM proxy has
  no Files API backend, so the previous unconditional upload failed.)
- **#104** — the Files API provider factory honors `*_BASE_URL` env vars, so
  binary/PDF uploads can route through a proxy that supports `/v1/files`.

Routing Colmena through the proxy uses `provider:"openai"` + `OPENAI_BASE_URL=
<proxy>/v1` + `OPENAI_API_KEY=<proxy master key>`, with the model alias resolved
by the proxy.

---

## 7. Cost model

USD is computed from `harness/pricing_table.json` (a dated snapshot), applying the
cached-input discount where the provider reports cached tokens:
`usd = (uncached_in·in_rate + cached·cached_rate + out·out_rate) / 1e6`. USD is
dominated by input tokens at temperature 0; the input-token multiple is the
robust headline figure.

---

## 8. Lines-of-code methodology

LOC is reported for the **node-vs-code** discussion but is measured conservatively
so it withstands scrutiny:
- **Excluded:** blank lines, comments, docstrings, and prompt/instruction string
  literals (prompt *content* is identical across frameworks — shared via
  `bench_common.scenario05` — so it is not framework code).
- **Colmena's DAG JSON is reported separately as declarative config, not code.**
- Two figures are given: **Code LOC** (handler `.py`, the two exclusions applied)
  and **Agent-construction LOC** (only the lines that stand up the agent/tool/
  memory — excludes imports and the benchmark replay loop).

See the demo doc for the numbers and an honest reading (in the *simple multi-turn*
demo, LOC does **not** favor Colmena — that pitch belongs to a production-agent
demo, not this one).

---

## 9. Reproducing

```bash
# 1. one-time: build all venvs + the Colmena binding
./scripts/setup_all.sh

# 2. a single-shot task across all 6 frameworks (e.g. hello world)
./scripts/run_task.sh 01

# 3. the hero multi-turn demo (proxy lifecycle handled inside)
./scripts/run_demo05.sh
# → runs/demo05/report/report.md  +  chart_data.json  +  quality_check.md
```

The Colmena binding must be built from `develop` (now includes #103/#104).

---

## 10. Task / demo catalog

| Task | What it measures | Status |
|---|---|---|
| **Task 1** — hello world | Per-call scaffolding overhead (tokens for a trivial agent) | done |
| **Task 4** — CSV analytical | Naive (CSV in context) vs expert (SQL tool) — a *strategy* difference, secondary | partial |
| **Demo 05** — context tax | Multi-turn cumulative tokens with an attachment + binary tool outputs — **hero** | **done (6 frameworks, live)** |

Planned hero demos #2 (outbound masking), #3 (durable HITL), #4 (production agent
in JSON — the real node-vs-code) are specced in the strategy doc.
