# Concurrency / Resource Load-Test — Design (demo13)

**Status:** Approved (brainstorm complete 2026-06-24)
**Author:** daniel + Claude

---

## 1. Goal

Measure, fairly and provider-independently, **how well Colmena handles many concurrent
agent requests on a single endpoint** versus the 5 Python frameworks (CrewAI, LangChain,
LangGraph, LlamaIndex, Google ADK) — on the axes where a Rust/tokio runtime *can* honestly
win: **concurrency capacity, resource footprint (RAM over time, not just peak), and
per-request overhead.**

This is a new demo (`demo13-concurrency`) in the same spirit as demo05/demo10: one
controlled experiment, provider-authoritative-by-construction (no LLM in the loop during
measurement), and **honest above all** — if the win doesn't appear under the ideal
instrument, we say so and stop.

## 2. The honesty frame (read this before designing anything)

The earlier code audit (`colmena-real-differentiators` memory; engine `develop`) established
what we may and may not claim. This design respects it:

| Axis | Claim? | Why |
|---|---|---|
| **Intra-run parallelism** (nodes of one agent run in parallel) | **NO** | The engine drains a **sequential worklist** (`engine.rs`: `while let Some(result) = stream.next().await`; no `tokio::spawn`/`join_all` over nodes). Claiming it would lose under scrutiny. |
| **Server-level concurrency** (N *independent* agent requests at once) | **YES, if verified** | Colmena `dag_engine` has a `Serve` mode (`serve <graph> --host --port 3000`) on a tokio runtime with a shared `PgPoolRegistry`/`Arc<PgPool>`. **Open risk:** Serve must dispatch a task per request, not serialize. Phase 1 verifies this. |
| **Execution time** | **Only the non-LLM overhead** | End-to-end wall-clock is dominated by LLM latency, identical for all 6. We isolate the framework's own contribution. |
| **RAM (time series + per session)** | **YES, likely** | Rust binary vs Python interpreter; lower per-node overhead. Direction the audit already supported. |

Two fairness rules that constrain the build:

1. **Production-vs-production deployment.** Every Python framework runs in a long-running
   server (FastAPI/uvicorn) with its **own warm connection pool**, exactly like Colmena
   `Serve`. We do **not** compare a warm Rust server against cold per-request Python
   subprocesses.
2. **The warm-pool DB advantage is NOT claimed as a framework win.** It is a deployment
   property available to everyone. The durable Rust win is what survives a fair fight:
   RAM/session, CPU/request, and how throughput + tail latency degrade under the GIL.

## 3. The measurement instrument: a fixed-latency LLM mock

We do **not** run the load sweep against a real LLM. Tokens are irrelevant here — only
resource and concurrency behavior matter — and a real LLM injects network variance and
provider rate-limits that contaminate the measurement.

- **Calibration (one time, ~cents of tokens):** issue ~20 real calls to `gemini-2.5-flash`
  through the existing proxy, record p50/p95 per-call latency. This sets the mock's fixed
  delay so the numbers are representative of a real Flash deployment.
- **The mock** (`harness/loadtest/stub_llm.py`): an OpenAI-compatible HTTP endpoint that,
  for any chat-completion request, sleeps a **fixed** configurable delay (default = the
  calibrated Flash p50) and returns a **canned** response — first a tool-call to the single
  workload tool, then on the follow-up a short final answer. No model, no tokens.
- All six servers point their LLM `base_url` at the mock (the runners already route LLM
  calls through a configurable `base_url`; see `proxy-bypass-native-providers` memory).
- **Why this is the fair ruler:** every framework waits *exactly the same* per LLM call, so
  the only thing that differs across the six is **how each runtime schedules N concurrent
  waits and what it costs in RAM/CPU per session.**

Only `gemini-2.5-flash` is used (for calibration). No `gemini-2.5-pro` (it would only make
the LLM dominate more and reveal *less* framework overhead).

## 4. The workload (identical for all 6)

A minimal fixed graph, byte-identical in semantics across frameworks:

```
LLM call #1  →  tool call: run_sql("SELECT count(*) FROM orders")  →  LLM call #2 (final answer)
```

- Two mock LLM calls + one trivial DB query per request. Short on purpose: lets us push
  concurrency very high and repeat thousands of times cheaply, maximizing the signal from
  framework overhead / RAM / connection handling rather than from "work."
- Colmena: a fixed DAG (`harness/loadtest/graphs/loadtest_minimal.json`) executed by `Serve`.
- Python frameworks: the idiomatic 1-tool agent loop each already has, wired to the same
  `run_sql` over the same SQLite/Postgres `orders` table used elsewhere in the bench.
- The DB table and `run_sql` result format match the existing bench tooling so the work is
  genuinely equivalent.

## 5. Architecture / components

```
                 ┌─────────────────────────┐
   load driver ──┤  POST /run  (one agent) ├── server: colmena Serve  ─┐
  (closed-loop)  └─────────────────────────┘                          │   each server's
       │                                   ...one warm server per fw   │   LLM base_url →
       │         resource sampler  (psutil, 100 ms, RSS+CPU per pid)   │   fixed-latency mock
       └─────────────────────────────────────────────────────────────┘
```

1. **Servers (one per framework), `runners/<fw>/server/`:**
   - Colmena: native `dag_engine serve <loadtest_minimal.json> --port <p>`.
   - 5 Python: thin FastAPI/uvicorn app exposing `POST /run`, holding a **warm asyncpg
     pool** and a **pre-constructed agent**, executing the minimal workload. One worker
     process unless a framework's idiomatic production deploy is multi-worker (documented
     per framework; if multi-worker is used, RAM is summed across workers for fairness).
2. **Fixed-latency LLM mock** (`harness/loadtest/stub_llm.py`) — §3.
3. **Load driver** (`harness/loadtest/driver.py`) — closed-loop async (httpx). Sweeps
   concurrency `C ∈ {1,2,4,8,16,32,64,128}` (extend until saturation). Per level: warmup,
   then fixed-duration steady state (default 30 s). Records per-request start/end → latency
   distribution + completed-count → throughput. Records errors (timeout/conn-refused/5xx).
4. **Resource sampler** (`harness/loadtest/sampler.py`) — samples each server's full process
   tree (server + workers) every 100 ms via psutil: RSS and CPU time. Emits a time series
   per (framework, concurrency level).
5. **Aggregator + plots** (`harness/loadtest/aggregate.py`) — computes the §6 metrics and
   writes `runs/demo13/` JSON + charts.

All new code lives under `harness/loadtest/` and `runners/<fw>/server/`; nothing in the
existing demos changes.

## 6. Metrics & win criteria

Single condition (mock calibrated to Flash). For each framework, at each concurrency level:

| # | Metric | Definition | Winner |
|---|---|---|--:|
| 1 | **Throughput ceiling** | plateau of completed agent-runs/sec across the sweep | highest |
| 2 | **Useful concurrency** | largest `N` where p95 latency ≤ 2× the `C=1` baseline latency | highest |
| 3 | **RAM per session** | `(RSS at N − idle RSS) / N`; also report full RSS-over-time curve and AUC | lowest |
| 4 | **CPU-sec per request** | total server CPU time / completed requests | lowest |
| 5 | **Saturation / error onset** | the `N` at which timeouts or 5xx begin | highest |

Reported as curves (throughput-vs-C, p99-vs-C, RAM-over-time, RAM-per-session-vs-C,
CPU-per-request) plus a summary table.

**Honest expectation:** Rust should win 1, 3, 4, 5; metric 2 may tie at low `N` and separate
as `N` rises. **If Colmena does not win under the mock** (the instrument most favorable to
it), there is no story — we record the null result and stop, as we did for demos 11/12.

## 7. Phasing (de-risk before building 5 servers)

- **Phase 1 — go/no-go gate.** Build: mock + driver + sampler + aggregator, Colmena `Serve`,
  and **one** Python server (LangGraph). Verify (a) `Serve` truly dispatches concurrent
  requests (not serialized) and (b) a real RAM/overhead gap exists. **Decision point:** if
  Serve serializes or the gap is absent, stop or re-scope.
- **Phase 2 — full field.** Add the remaining 4 Python servers (CrewAI, LangChain,
  LlamaIndex, Google ADK).
- **Phase 3 — report.** Final sweep, plots, and a write-up (`docs/demos/demo13-concurrency.md`)
  with the honesty framing of §2 baked in. Optionally feed one chart into the existing
  whitepaper/brief if the win is clean.

## 8. Open risks (carry into the plan)

1. **`Serve` concurrency model unverified.** If `Serve` serializes runs, Colmena's
   concurrency story collapses; mitigation in Phase 1: inspect the serve handler
   (`dag_engine/api.rs`) and empirically confirm concurrent dispatch; if needed, run N
   `Serve` workers behind the driver and document it.
2. **Cross-language RSS baseline.** A Python interpreter's idle RSS ≠ a Rust binary's. We
   report **both** absolute RSS-over-time **and** the marginal RAM-per-session (which
   subtracts idle baseline) so the comparison is honest about what is fixed cost vs.
   per-session cost.
3. **Per-framework deploy idioms.** Some frameworks are idiomatically multi-worker
   (uvicorn `--workers`). We document each framework's chosen deploy and, when multi-worker,
   sum RAM/CPU across workers so no one is unfairly advantaged or penalized.
4. **DB as shared bottleneck.** All servers hit the same DB; the trivial `count(*)` keeps DB
   cost negligible so it is not the limiter. If DB becomes the bottleneck, switch the tool to
   a pure in-process computation (no DB) and note it.
5. **Mock fidelity.** The fixed delay is a simplification of real LLM latency variance; we
   disclose this and note the mock is an *instrument* for isolating runtime behavior, not a
   claim about end-to-end production latency.

## 9. Out of scope (YAGNI)

- Real-LLM end-to-end load testing (mock is the instrument; real Flash only calibrates it).
- `gemini-2.5-pro` or any second model.
- Intra-run parallelism claims of any kind.
- Multi-host / distributed load generation (single-host driver is sufficient at this scale).
- Changing any existing demo.

## 10. Success criteria

1. A reproducible single-host load harness (mock + driver + sampler + aggregator) under
   `harness/loadtest/`.
2. Phase 1 produces a clear go/no-go with `Serve` concurrency empirically verified.
3. The 5 metrics of §6 computed for all 6 frameworks with charts in `runs/demo13/`.
4. A write-up that leads with the §2 honesty framing (no parallelism claim; warm-pool not
   claimed as a framework win) and reports the null result honestly if the win is absent.
