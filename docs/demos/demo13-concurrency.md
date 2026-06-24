# Demo 13 — Concurrency & resource load-test (NULL RESULT, recorded honestly)

**This demo does NOT show a Colmena win, and we keep it to prove the point.** It was
built to test whether Colmena's Rust/tokio runtime handles many concurrent agent
requests better than the Python frameworks. It does not. We record the result because
the discipline of this benchmark is to publish what we measured — the same discipline
that dropped demos 11 and 12.

The one thing Colmena *does* win here — a **~4× smaller absolute memory footprint** — is
real but cannot be converted into throughput, and we frame it honestly below.

---

## 1. What was measured

A fair, production-vs-production concurrency load-test:

- **Instrument, not the LLM.** A fixed-latency OpenAI-compatible **mock** (`harness/loadtest/stub_llm.py`)
  replaces the model: every "LLM call" waits the same fixed delay (~600 ms here) and
  returns a canned tool-call then a final answer. No tokens are spent during the sweep.
  This is *more* fair than a real LLM — it removes network variance and provider
  rate-limits, so the only variable left is **how each runtime schedules concurrent
  waits and what it costs in RAM/CPU**.
- **Workload** (identical for both): one agent request = LLM call → `run_sql` tool
  (an HTTP call to the mock) → final LLM call. Minimal on purpose, so concurrency — not
  "work" — is what is exercised.
- **Deployment** (production-vs-production): Colmena's native `dag_engine serve` (warm,
  pooled) vs a **warm async** LangGraph FastAPI server (`runners/langgraph/runner/server/app.py`,
  `AsyncClient` + `agent.ainvoke`, one worker). Both hold warm state; neither pays
  per-request startup.
- **Load**: a closed-loop driver (`harness/loadtest/driver.py`) sweeping concurrency
  C = 1, 2, 4, 8, 16, 32, 64; a psutil sampler (`harness/loadtest/sampler.py`) records
  each server process tree's RSS and CPU over time.

Reproduce: `set -a && source .env && set +a && DURATION_S=15 CONCURRENCIES=1,2,4,8,16,32,64 bash harness/loadtest/run_phase1.sh`
then `.venv-bench/bin/python -m harness.loadtest.phase1_verdict`.
Artifacts: `runs/demo13/phase1/{colmena,langgraph}.json`, `runs/demo13/phase1/VERDICT.md`.

---

## 2. Result — Colmena `Serve` serializes under load

| C | Colmena throughput | Colmena p95 | LangGraph throughput | LangGraph p95 |
|--:|--:|--:|--:|--:|
| 1 | 0.9 rps | 1.29 s | 0.8 rps | 1.22 s |
| 2 | 1.6 rps | 1.32 s | 1.6 rps | 1.23 s |
| 4 | **2.6 rps** | 1.63 s | 3.2 rps | 1.24 s |
| 8 | 2.6 rps | 3.09 s | 6.5 rps | 1.25 s |
| 16 | 2.6 rps | 6.09 s | 12.9 rps | 1.27 s |
| 32 | 2.6 rps | 11.98 s | 25.6 rps | 1.30 s |
| 64 | 2.5 rps | **19.41 s** (+22 timeouts) | **50.4 rps** | 1.44 s |

**Colmena throughput flatlines at ~2.6 rps from C=4 onward while its p95 latency grows
linearly** (1.3 s → 19.4 s) and requests start timing out at C=64. That is the textbook
signature of **serialized execution**: the server accepts concurrent connections but
processes the underlying work one-at-a-time, so added concurrency only lengthens the
queue. Colmena's axum layer *does* spawn a task per connection, so the bottleneck is a
global lock / shared state inside the engine, **not** the HTTP front door.

**LangGraph (a single async worker) scales linearly to 50.4 rps** at C=64 with flat
~1.2–1.4 s p95 and zero errors — healthy async concurrency. It out-scales Colmena's
throughput ceiling by **~20×**.

This empirically confirms what the earlier code audit already flagged: the engine is a
**sequential worklist**; Rust buys lower per-node overhead and RAM, **not** parallelism
or throughput. We do not pitch concurrency or "agents handled per endpoint".

---

## 3. The one real win — absolute memory footprint (~4× smaller at idle, ~2× at peak)

| | idle RSS | RSS at C=64 |
|---|--:|--:|
| **Colmena** | 28 MB | 65 MB |
| **LangGraph** | 122 MB | 132 MB |

Colmena's absolute resident memory is **~4.4× lower at idle, narrowing to ~2× at peak
load** (C=64) — its RSS climbs under the request queue while LangGraph's stays flat. It is
still a real, defensible Rust advantage: **at idle a Colmena instance fits in roughly a
quarter of the RAM** of a Python agent server (about half at peak load).

**Two honesty caveats we state up front:**
1. **Marginal RAM-per-session is *not* a Colmena win.** Colmena's per-session increment
   (~0.58 MB/session) is actually *higher* than LangGraph's (~0.16 MB above its ~122 MB
   baseline). The win is purely the **absolute floor** (Rust binary vs Python interpreter),
   not per-request scaling.
2. **Low memory does not become throughput.** Because `Serve` serializes, the small
   footprint can't be traded for more concurrent load. You can pack more Colmena
   instances per host, but each instance still tops out at ~2.6 rps on this workload.

So the only claim this demo supports is **"lower absolute memory footprint per
instance"** — never "handles more concurrent load".

---

## 4. Why this is a NULL result, not a hidden win

A multi-process deployment (N `Serve` workers behind a balancer) could raise aggregate
throughput, but LangGraph reached 50 rps in *one* async worker; Colmena would need on the
order of ~20 processes to match, at which point the per-instance RAM advantage is diluted
by process count. There is no framing under which Colmena wins the concurrency/throughput
axis on this evidence. We stop here and do not build the remaining four framework servers
(the planned "Phase 2") — there is no win to generalize.

The harness itself is sound and reusable (`harness/loadtest/`), so if the Colmena engine
ever gains concurrent DAG execution, re-running this sweep is a one-command check.

---

## 5. Files

- Harness: `harness/loadtest/{stub_llm,sampler,driver,aggregate,run_phase1_drive,phase1_verdict,calibrate}.py`, `harness/loadtest/run_phase1.sh`
- Colmena graph: `harness/loadtest/graphs/loadtest_minimal.json`
- LangGraph server: `runners/langgraph/runner/server/app.py`
- Results: `runs/demo13/phase1/{colmena,langgraph}.json`, `runs/demo13/phase1/VERDICT.md`
- Spec / plan: `docs/superpowers/specs/2026-06-24-concurrency-loadtest-design.md`, `docs/superpowers/plans/2026-06-24-concurrency-loadtest.md`
- Memory note: `demo13-concurrency-loadtest`
