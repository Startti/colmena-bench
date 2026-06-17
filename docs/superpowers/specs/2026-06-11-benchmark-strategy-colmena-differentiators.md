# Benchmark Strategy — Selling Colmena on Its Real Differentiators

**Date:** 2026-06-11
**Status:** strategic reframe (supersedes the "CSV asymptote as hero" framing)

## Why this document exists

The end goal of colmena-bench is to **sell Colmena as the better choice**. A
benchmark only sells if (a) it measures where Colmena genuinely wins and (b)
it is demonstrably fair (same harness, provider-authoritative tokens, pinned
versions, adversarial review). Building the hero demo on an axis where Colmena
ties or loses backfires under scrutiny.

Today's data + a code-level audit of `Startti/colmena@develop` forced a
reframe. This doc records where Colmena actually wins, what to drop, and the
demos to build.

## The uncomfortable findings (measured / code-verified)

1. **Token cost is framework-independent for the same strategy.** All six
   runners call the same model through the same proxy. "Answer 20 questions
   with a SQL tool" costs ~the same tokens everywhere. The CSV naive-vs-expert
   asymptote (old Task 4) is a *strategy* difference, not a *framework* one —
   weak for selling Colmena specifically. Keep it as a secondary
   data-analytics result, not the hero.
2. **LOC on hello-world is a wash.** Measured from real runner code: Colmena
   83, CrewAI 80, LangChain 51, ADK 85. The node-vs-code advantage does NOT
   show on trivial agents.
3. **Colmena is NOT broadly parallel.** The DAG engine is a sequential
   worklist (`run_use_case.rs:291`, `pop_front`, one node awaited at a time);
   even orchestrator `parallel: true` tasks are awaited in a sequential loop
   (no spawn/join). **Do NOT pitch "runs more agents concurrently"** — we lose
   to LangGraph/CrewAi. Rust buys lower per-node overhead + RAM, not
   throughput. (This kills the old Task 7 concurrency demo.)

## Where Colmena genuinely wins (build the demos here)

Ranked. Each: claim · evidence · metric · competitor reality.

### #1 — Context scrubbing (THE killer demo)
- **Claim:** Colmena keeps large blobs/binaries/tool-outputs OUT of the LLM
  history; the others accumulate them every turn.
- **Evidence:** always-on tool-result scrubber elides base64/oversize payloads
  (`dag_tool_executor.rs:1744-1823`, "always-on … megabytes of useless
  tokens"); attachment catalog + ephemeral `load_attachment` + forward-without
  -reading (`docs/developer_guide/31_load_attachment.md`): the model sees a
  ~30-token catalog line, can read a doc for one turn only (not persisted),
  forward bytes with ~50 tokens, or ignore.
- **Metric:** total prompt tokens + USD across a **multi-turn conversation
  with a large/binary attachment** (e.g. a 10–50pp PDF, then 5 follow-ups).
  Colmena pays the doc ≤once; the 5 Python frameworks pay it every turn → a
  gap that **compounds with turn count**. This is the real asymptote, measured
  by the proxy we already built.
- **Competitor reality:** none of the 5 has an always-on binary scrubber or a
  read/forward/ignore attachment catalog. Genuine, unique win.
- **✅ DONE (2026-06-16) — measured, all 6 frameworks, live.**
  Fixed 10-turn report-assistant conversation (doc summarize + region/growth/
  risk questions + 3 chart-generation turns), same model (`gemini-2.5-flash`),
  same proxy, provider-authoritative tokens bucketed per turn.
  - **Total input tokens:** colmena **37,134** vs competitor cluster
    **385,312–452,428** (median 432,002) → **~11.6x** total-token tax this run.
    (Colmena varies ~37k–66k run-to-run as the model chooses when to re-read the
    doc; competitors stable; the gap is consistently **≥6x**.)
  - **Turn-10 input tokens:** colmena **1,951** vs competitor median
    **71,170** → **~36x** per-turn tax at turn 10 (and growing).
  - **USD (10 turns):** colmena **$0.016988** vs competitor median
    **~$0.135** → **~7.9x**.
  - **Curve:** colmena cumulative-input stays comparatively flat; the 5
    competitors grow roughly linearly in history (jumps at the doc turn and at
    every chart turn). Caused by built-in ephemeral `load_attachment` (doc not
    pinned in history) + always-on base64 tool-output scrubbing (chart bytes
    elided) — zero extra code.
  - **Quality kept:** colmena's doc-turn answers are correct (turn 1 "North
    America", turn 7 "Supply chain", turn 0 "positive"); its only empty turns
    are the 3 legitimate chart turns. The token win is NOT a quality trade.
    Honest caveat: the llamaindex run returned empty text on turns 3–4 (its own
    agent quirk; exited 0, no crash) — noted but does not affect tokens.
  - **Engine fixes MERGED to `develop` (2026-06-17):** colmena #103 (inline text
    attachments skip the provider Files API → served via `load_attachment` from
    storage) + #104 (Files API factory honors `*_BASE_URL`). The bench binding is
    now built from `develop` (no local-branch dependency); verified end-to-end
    with a fresh session (real doc answers + base64 charts elided).
  - **Report:** `runs/demo05/report/report.md` (+ `chart_data.json`,
    `quality_check.md`). **Design spec:**
    `docs/superpowers/specs/2026-06-16-context-scrubbing-demo-design.md`.
  - **LOC (after slimming the handler via `inject_payload`):** the agent is a
    declarative DAG (~71-line JSON, not code); the Python runner is thin. Counting
    maintained imperative code, colmena is the **leanest** of the six — **53 LOC**
    vs 67–124. Honest framing: disclose the 71-line DAG; the claim is "smaller
    maintained code AND free context management." The gap widens with complexity;
    the amplified node-vs-code win is demo #4.

### #2 — Encrypted secrets + outbound masking (security)
- **Claim:** credentials are injected as opaque handles; the plaintext never
  reaches the model, even in tool results.
- **Evidence:** AES-256-GCM `secure_value_mappings`, `inject_secrets` +
  `mask_outbound` before tool results reach the model
  (`dag_tool_executor.rs:1667-1681`, `13_security_strategy.md`,
  `tests/outbound_masking_integration.rs`).
- **Metric:** binary pass/fail — "inject a credential into a tool; prove the
  plaintext appears in zero LLM-visible messages."
- **Competitor reality:** none of the 5 has built-in encrypted-secret +
  outbound masking. Novel.

### #3 — Native durable HITL suspend/resume (cross-process)
- **Claim:** pause for human input, survive process death, resume in a new
  process — and it bubbles through nested orchestrators/subgraphs.
- **Evidence:** `suspend`/`secure_suspend` nodes, Postgres snapshot keyed by
  `agent_session_id`, `compute_resuming_node_ids`
  (`run_use_case.rs:256-267`), 4-point orchestrator HITL
  (`44_suspend_node.md`, `20_orchestrator_architecture.md:219-329`).
- **Metric:** LOC to add an approval gate + "survives process restart? y/n".
- **Competitor reality:** **rough parity with LangGraph** (checkpointers +
  interrupt) — be honest. Clear win over CrewAI/LangChain/LlamaIndex (you build
  the state store yourself).

### #4 — Production agent in JSON, no code (node vs code)
- **Claim:** a prod-ready agent (HITL + retries + critic + security) is a
  declarative JSON DAG, not framework glue code.
- **Evidence:** `tests/graphs/basic/suspend_email_approval_demo.json` (61 lines
  JSON: draft → suspend(approval) → router → send/cancel/revise, zero code);
  bundled planner→critic→reactor loop with retry+feedback injection +
  bridge-task replanning (`20_orchestrator_architecture.md`).
- **Metric:** config-LOC + #files to stand up the approve/reject/revise flow;
  auto-recovery rate from a deliberately-incomplete first agent output (critic
  loop).
- **Competitor reality:** strong vs the code-first 3 (CrewAI/LangChain/
  LlamaIndex); **parity on "it's a graph" with LangGraph/ADK** — so the pitch
  is the *bundled prod-hardening*, not "it's a graph."

### Honorable mentions (measurable, secondary)
- **SQL node guardrails** (RLS/permission presets/sandbox) — `23_sql_node.md`;
  competitors expose raw SQL tools, you write the guards.
- **API Explorer node** (runtime OpenAPI discovery).
- **CRDT collaborative docs** — great live "wow", weak as a metric.

## Foundational enabler (prerequisite for #1, #2, #3)

The current Colmena runner drives a single-shot `ColmenaLlm.call`. Demos #1–#3
need Colmena to execute **real DAGs** with tool nodes, attachments, suspend.
**Build a `runDag` driver** for the Colmena runner. Python binding (verified):

    run_dag(file_path, resume_id=None, resume_answer=None, inject_payload=None,
            include_extra_info=False, agent_session_id=None) -> str  # JSON result

DAG shape (verified from `tests/graphs/`): `{"nodes": {id: {"type":"llm_call",
"config": {"provider","api_key":"${ENV}","model","prompt","enabled_tools",
"connection_url":"${DATABASE_URL}"}}}, "edges":[...]}`.

Routing through the proxy: `provider:"openai"` + `OPENAI_BASE_URL=<proxy>/v1` +
`OPENAI_API_KEY=<proxy master key>`, model = the alias. (Same trick as the
single-shot path.)

**HARD PREREQUISITE — Postgres.** `run_dag` fails with `DATABASE_URL must be set
to build ColmenaEngine`. The DAG engine needs Postgres for run snapshots,
`llm_node_history`, attachments, and `secure_value_mappings` — i.e. the very
machinery that powers suspend/resume (#3) and attachment scrubbing (#1).

**✅ RESOLVED (2026-06-16): `run_dag` works end-to-end.** The earlier "hang"
was NOT a hang — it was three independent, fixable issues in the bench's
Colmena binding, each masking the next. Root causes + fixes:

1. **Stale binding (pre-fix).** The bench binding was built Jun 11; the engine
   `run_dag` fix landed in `develop` on Jun 14 (`engine.run_dag` routed to the
   deprecated `DagRunUseCase::execute()` stub = `unimplemented!`, instead of
   draining `execute_stream`; see `audit_python_bindings.md` P1). The old binding
   panicked `run_use_case.rs:100: not implemented: execute() is deprecated` on
   *every* graph. **Fix:** rebuild from current `develop`.
2. **Wrong maturin build.** Rebuilding with `maturin develop --features python`
   from the crate dir omits `pyo3/extension-module` and the root `pyproject.toml`
   `[tool.maturin]` config → runtime `Fatal Python error: PyInterpreterState_Get
   … GIL … released`. **Fix:** run `maturin develop --release` from the REPO
   ROOT (`/Users/danielgarcia/startti/colmena`) so it uses
   `features = ["pyo3/extension-module", "python"]`, `module-name = "colmena"`,
   `python-source = "stubs"`. Builds into the active venv (set `VIRTUAL_ENV` to
   `runners/colmena/.venv`, Python 3.11 — pyo3 0.21 supports ≤3.12).
3. **Missing `SECURE_VALUES_KEY`.** The Postgres secure-value backend refuses to
   start without a ≥32-char pgcrypto key (`postgres_secure_value_repository.rs`)
   — it panics with a clear message (it was never a silent hang). **Fix:**
   `SECURE_VALUES_KEY` in `.env`.

Verified: `power.json` (pure compute, no DB) → `pow_step.output = 125.0`;
`smoke_hello.json` (LLM node) through the proxy + the GCP Colmena DB →
`result: "hello"`, `usage {prompt 246, completion 1}`, and the proxy captured a
matching span (`tokens_input 246, tokens_output 1, latency 728ms, ok:true`) —
**token parity on the DAG path confirmed.** The DB was always healthy; nothing
was environment-specific. Demos #1/#2/#3 are now unblocked.

**Proxy footgun fixed alongside.** `DATABASE_URL` in `.env` made LiteLLM
auto-start its (uninstalled) Prisma client and refuse to boot. `unset`/empty
don't work (LiteLLM reloads `.env` via python-dotenv from its package dir under
`.venv-bench`, and treats `""` as present via an `is None` check). **Fix:** store
the Colmena DB as `COLMENA_DATABASE_URL` in `.env`; the DAG path re-exports it as
`DATABASE_URL` for its own subprocess. Proxy never sees it.

**Reproduce the working DAG path:**
```bash
# 1. rebuild binding (once, after pulling colmena develop)
cd /Users/danielgarcia/startti/colmena
VIRTUAL_ENV=/Users/danielgarcia/startti/colmena-bench/runners/colmena/.venv \
  PATH="$VIRTUAL_ENV/bin:$PATH" maturin develop --release
# 2. proxy up (reads .env, ignores COLMENA_DATABASE_URL)
cd /Users/danielgarcia/startti/colmena-bench
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=dagsmoke ./proxy/start_proxy.sh &
# 3. run a DAG: export DATABASE_URL=$COLMENA_DATABASE_URL, OPENAI_API_KEY=$LITELLM_MASTER_KEY,
#    OPENAI_BASE_URL=.../v1, SECURE_VALUES_KEY set → colmena.run_dag(...)
```

The single-shot `ColmenaLlm.call` path (Tasks 1 + 4-naive) also works.
Competitors' demos use their native agent+tool APIs (CrewAI tool path works).

## Build sequence (proposed)

1. **Colmena `runDag` driver** (enabler) + a trivial tool DAG smoke.
2. **Demo #1 — context scrubbing asymptote**: a multi-turn + attachment task
   across all 6; the proxy measures accumulated tokens. This is the hero.
3. **Demo #4 — node-vs-code + LOC**: the approve/reject/revise agent in all 6;
   measure config/code LOC + reliability.
4. **Demo #2 — outbound masking** (binary security pass/fail).
5. **Demo #3 — durable HITL** (LOC + survives-restart), honest LangGraph parity.

Each demo is its own spec → plan → implement cycle. Charts and whitepaper come
after the data exists.

## What we explicitly drop
- Concurrency/throughput "100 agents" demo (old Task 7) — engine is sequential.
- CSV asymptote as the hero (keep as secondary data-analytics result).
- Generic observability / multi-provider routing as headline (parity).
