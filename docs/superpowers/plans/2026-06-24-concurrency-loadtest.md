# Concurrency / Resource Load-Test (demo13) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-host load-test harness that measures, against a fixed-latency LLM mock, how Colmena's `Serve` and each Python framework's warm server handle concurrent agent requests — throughput, tail latency, RAM-over-time, and CPU/request.

**Architecture:** A fixed-latency OpenAI-compatible mock replaces the LLM so the only variable is each runtime's concurrency/RAM behavior. A closed-loop async driver sweeps concurrency levels against each framework's warm HTTP server; a psutil sampler records the server process-tree's RSS+CPU; an aggregator computes five win-metrics. Colmena uses its native `dag_engine serve`; Python frameworks get a thin FastAPI wrapper.

**Tech Stack:** Python 3.11 (`.venv-bench`), FastAPI + uvicorn, httpx (async), psutil, pytest; Colmena `dag_engine` (Rust/axum) via `serve`.

**Scope note:** This plan implements **Phase 1 only** (the go/no-go gate from the spec: mock + sampler + driver + aggregator + Colmena `Serve` + the LangGraph server). Phases 2–3 (the other 4 servers; final sweep + write-up) are outlined at the end and get their own detailed plan **after** the Phase 1 verdict, because they are contingent on Phase 1 confirming `Serve` is concurrent and the win exists.

**Spec:** `docs/superpowers/specs/2026-06-24-concurrency-loadtest-design.md`

**Phase-1 deviation from spec §4 (documented, allowed by spec §8.4):** the workload tool is a **trivial constant-returning HTTP endpoint on the mock** (`POST /tool`), not a SQL query. This isolates *runtime* concurrency for the go/no-go and removes the DB as a confound. The DB-backed `run_sql` variant is added in Phase 2. The workload remains LLM→tool→LLM, identical for all frameworks.

---

## File Structure

**New package `harness/loadtest/`:**
- `__init__.py` — empty package marker.
- `stub_llm.py` — fixed-latency OpenAI-compatible mock + trivial `/tool` endpoint. CLI runnable.
- `sampler.py` — `ResourceSampler`: psutil process-tree RSS+CPU time-series + `summarize()`.
- `driver.py` — `run_level()` / `run_sweep()`: closed-loop async load generator.
- `aggregate.py` — `compute_metrics()`: the five win-metrics from driver+sampler output.
- `phase1_verdict.py` — go/no-go analysis: Serve-concurrency check + win/null verdict.
- `graphs/loadtest_minimal.json` — Colmena DAG: webhook `/run` → llm → `run_sql` http tool → llm.
- `run_phase1.sh` — orchestration: start mock + servers, run sweep, aggregate, verdict.
- `calibrate.py` — one-time: measure real Gemini 2.5 Flash latency → `runs/demo13/calibration.json`.
- `tests/` — `test_stub_llm.py`, `test_sampler.py`, `test_driver.py`, `test_aggregate.py`.

**New Python server `runners/langgraph/server/`:**
- `__init__.py` — empty.
- `app.py` — FastAPI app: warm `create_react_agent` + httpx client, `POST /run`.

**Outputs:** `runs/demo13/phase1/` (per-framework JSON + `VERDICT.md`), `runs/demo13/calibration.json`.

**Conventions:** all Python run via `.venv-bench/bin/python`. No global python. Mock/tool return only constants; no secrets, no tokens during the sweep.

---

### Task 1: Fixed-latency LLM mock + trivial tool endpoint

**Files:**
- Create: `harness/loadtest/__init__.py`
- Create: `harness/loadtest/stub_llm.py`
- Test: `harness/loadtest/tests/__init__.py`, `harness/loadtest/tests/test_stub_llm.py`

The mock is an OpenAI-compatible `/v1/chat/completions` endpoint that sleeps a fixed delay, then returns a **tool call** if the request has no prior `tool`-role message, else a **final answer**. It also serves `POST /tool` returning a constant instantly (the workload tool).

- [ ] **Step 1: Create the package markers**

```bash
mkdir -p harness/loadtest/tests harness/loadtest/graphs
touch harness/loadtest/__init__.py harness/loadtest/tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `harness/loadtest/tests/test_stub_llm.py`:

```python
import json
from fastapi.testclient import TestClient
from harness.loadtest.stub_llm import build_app


def _client(delay_ms=0):
    return TestClient(build_app(delay_ms=delay_ms))


def test_first_call_returns_tool_call():
    c = _client()
    r = c.post("/v1/chat/completions", json={
        "model": "gemini-2.5-flash",
        "messages": [{"role": "user", "content": "count orders"}],
    })
    assert r.status_code == 200
    body = r.json()
    msg = body["choices"][0]["message"]
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    assert msg["tool_calls"][0]["function"]["name"] == "run_sql"
    args = json.loads(msg["tool_calls"][0]["function"]["arguments"])
    assert "query" in args


def test_followup_with_tool_result_returns_final():
    c = _client()
    r = c.post("/v1/chat/completions", json={
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "user", "content": "count orders"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "run_sql", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "1000"},
        ],
    })
    body = r.json()
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["choices"][0]["message"]["content"]
    assert not body["choices"][0]["message"].get("tool_calls")


def test_tool_endpoint_returns_constant():
    c = _client()
    r = c.post("/tool", json={"query": "SELECT count(*) FROM orders"})
    assert r.status_code == 200
    assert r.json()["result"] == "1000"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_stub_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: harness.loadtest.stub_llm`.

- [ ] **Step 4: Implement the mock**

Create `harness/loadtest/stub_llm.py`:

```python
"""Fixed-latency, OpenAI-compatible LLM mock for the concurrency load-test.

The mock is the *measurement instrument*: every framework waits exactly the same
per "LLM call", so the only thing that differs under load is how each runtime
schedules concurrent waits and what it costs in RAM/CPU. No real model, no tokens.

Stateless rule: a chat request whose messages already contain a `tool`-role
message gets a final answer; otherwise it gets a single tool call to `run_sql`.
`POST /tool` is the workload tool — it returns a constant instantly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_TOOL_NAME = "run_sql"
_TOOL_QUERY = "SELECT count(*) FROM orders"
_TOOL_RESULT = "1000"
_FINAL_TEXT = "There are 1000 orders."


def _tool_call_response(model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock-tool",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_mock_1",
                    "type": "function",
                    "function": {
                        "name": _TOOL_NAME,
                        "arguments": json.dumps({"query": _TOOL_QUERY}),
                    },
                }],
            },
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _final_response(model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock-final",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": _FINAL_TEXT},
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def build_app(delay_ms: int = 0) -> FastAPI:
    app = FastAPI()
    delay_s = delay_ms / 1000.0

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        body = await request.json()
        if delay_s:
            await asyncio.sleep(delay_s)
        messages = body.get("messages", [])
        model = body.get("model", "mock")
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        payload = _final_response(model) if has_tool_result else _tool_call_response(model)
        return JSONResponse(payload)

    @app.post("/tool")
    async def tool(request: Request) -> JSONResponse:
        # Trivial workload tool — constant, instant. (DB variant is Phase 2.)
        return JSONResponse({"result": _TOOL_RESULT})

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--delay-ms", type=int, default=600)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build_app(delay_ms=args.delay_ms), host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_stub_llm.py -v`
Expected: PASS (3 passed). If `fastapi`/`httpx` missing, install into the bench venv: `.venv-bench/bin/pip install fastapi uvicorn httpx psutil`.

- [ ] **Step 6: Commit**

```bash
git add harness/loadtest/__init__.py harness/loadtest/stub_llm.py harness/loadtest/tests/__init__.py harness/loadtest/tests/test_stub_llm.py
git commit -m "feat(loadtest): fixed-latency OpenAI-compatible LLM mock + trivial tool endpoint"
```

---

### Task 2: Resource sampler (RSS + CPU time-series over the process tree)

**Files:**
- Create: `harness/loadtest/sampler.py`
- Test: `harness/loadtest/tests/test_sampler.py`

Samples a server's full process tree (parent + children) RSS and CPU at a fixed interval in a background thread, and summarizes peak/mean/AUC RAM and total CPU-seconds.

- [ ] **Step 1: Write the failing test**

Create `harness/loadtest/tests/test_sampler.py`:

```python
import os
import time
from harness.loadtest.sampler import ResourceSampler


def test_sampler_collects_series_and_summary():
    sampler = ResourceSampler(pid=os.getpid(), interval=0.02)
    sampler.start()
    # busy a little so CPU time advances and time passes
    end = time.time() + 0.3
    x = 0
    while time.time() < end:
        x += 1
    sampler.stop()
    series = sampler.series
    assert len(series) >= 3
    for sample in series:
        assert sample["rss_bytes"] > 0
        assert sample["t"] >= 0
    summary = sampler.summarize()
    assert summary["rss_peak_bytes"] >= summary["rss_mean_bytes"] > 0
    assert summary["rss_auc_bytes_s"] > 0
    assert summary["cpu_seconds"] >= 0.0
    assert summary["samples"] == len(series)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_sampler.py -v`
Expected: FAIL — `ModuleNotFoundError: harness.loadtest.sampler`.

- [ ] **Step 3: Implement the sampler**

Create `harness/loadtest/sampler.py`:

```python
"""Process-tree RSS + CPU sampler for the load-test.

Reports the full RAM-over-time curve (not just peak) and CPU-seconds, so we can
compute mean/peak/area-under-curve RAM and CPU-per-request. Samples in a daemon
thread; subtract idle baseline downstream to get marginal RAM-per-session.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import psutil


class ResourceSampler:
    def __init__(self, pid: int, interval: float = 0.1) -> None:
        self.pid = pid
        self.interval = interval
        self.series: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def _tree(self) -> list[psutil.Process]:
        try:
            proc = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            return []
        procs = [proc]
        try:
            procs.extend(proc.children(recursive=True))
        except psutil.NoSuchProcess:
            pass
        return procs

    def _sample_once(self) -> dict[str, float] | None:
        procs = self._tree()
        if not procs:
            return None
        rss = 0
        cpu = 0.0
        for p in procs:
            try:
                rss += p.memory_info().rss
                ct = p.cpu_times()
                cpu += ct.user + ct.system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"t": time.time() - self._t0, "rss_bytes": float(rss), "cpu_seconds": cpu}

    def _run(self) -> None:
        while not self._stop.is_set():
            s = self._sample_once()
            if s is not None:
                self.series.append(s)
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._t0 = time.time()
        self._stop.clear()
        self.series = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def summarize(self) -> dict[str, Any]:
        if not self.series:
            return {"samples": 0, "rss_peak_bytes": 0, "rss_mean_bytes": 0,
                    "rss_auc_bytes_s": 0.0, "cpu_seconds": 0.0}
        rss = [s["rss_bytes"] for s in self.series]
        # trapezoidal area under the RSS-vs-time curve
        auc = 0.0
        for a, b in zip(self.series, self.series[1:]):
            auc += (a["rss_bytes"] + b["rss_bytes"]) / 2.0 * (b["t"] - a["t"])
        cpu_seconds = self.series[-1]["cpu_seconds"] - self.series[0]["cpu_seconds"]
        return {
            "samples": len(self.series),
            "rss_peak_bytes": max(rss),
            "rss_mean_bytes": sum(rss) / len(rss),
            "rss_auc_bytes_s": auc,
            "cpu_seconds": max(0.0, cpu_seconds),
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_sampler.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add harness/loadtest/sampler.py harness/loadtest/tests/test_sampler.py
git commit -m "feat(loadtest): process-tree RSS+CPU time-series sampler"
```

---

### Task 3: Closed-loop async load driver

**Files:**
- Create: `harness/loadtest/driver.py`
- Test: `harness/loadtest/tests/test_driver.py`

Runs `C` concurrent virtual clients in a closed loop for a fixed duration against a `POST` endpoint, recording per-request latency, completed count → throughput, and errors.

- [ ] **Step 1: Write the failing test**

Create `harness/loadtest/tests/test_driver.py`. It spins up the mock in a background uvicorn thread and drives it.

```python
import threading
import time
import uvicorn
from harness.loadtest.stub_llm import build_app
from harness.loadtest import driver


class _Server:
    def __init__(self, app, port):
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(timeout=3)


def test_driver_reports_throughput_and_latency():
    port = 9211
    # delay 50ms per call; /tool path returns instantly
    with _Server(build_app(delay_ms=50), port):
        result = driver.run_level(
            url=f"http://127.0.0.1:{port}/tool",
            payload={"query": "x"},
            concurrency=4,
            duration_s=1.0,
        )
    assert result["concurrency"] == 4
    assert result["completed"] > 0
    assert result["throughput_rps"] > 0
    assert result["p50_ms"] >= 0
    assert result["p95_ms"] >= result["p50_ms"]
    assert result["errors"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_driver.py -v`
Expected: FAIL — `AttributeError: module 'harness.loadtest.driver' has no attribute 'run_level'`.

- [ ] **Step 3: Implement the driver**

Create `harness/loadtest/driver.py`:

```python
"""Closed-loop async load driver.

`C` virtual clients each loop: fire request -> await response -> fire next, with
no think time, for a fixed duration. Throughput = completed / wall_time;
latency percentiles from per-request samples. `run_sweep` walks concurrency
levels and returns one record per level.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


async def _worker(client, url, payload, deadline, latencies, counters):
    while time.monotonic() < deadline:
        t0 = time.monotonic()
        try:
            r = await client.post(url, json=payload)
            if r.status_code >= 500:
                counters["errors"] += 1
            else:
                latencies.append((time.monotonic() - t0) * 1000.0)
                counters["completed"] += 1
        except Exception:
            counters["errors"] += 1


async def _run_level_async(url, payload, concurrency, duration_s, warmup_s):
    counters = {"completed": 0, "errors": 0}
    latencies: list[float] = []
    limits = httpx.Limits(max_connections=concurrency * 2,
                          max_keepalive_connections=concurrency * 2)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        if warmup_s:
            wend = time.monotonic() + warmup_s
            warm = [asyncio.create_task(
                _worker(client, url, payload, wend, [], {"completed": 0, "errors": 0}))
                for _ in range(concurrency)]
            await asyncio.gather(*warm)
        deadline = time.monotonic() + duration_s
        start = time.monotonic()
        tasks = [asyncio.create_task(
            _worker(client, url, payload, deadline, latencies, counters))
            for _ in range(concurrency)]
        await asyncio.gather(*tasks)
        wall = time.monotonic() - start
    return {
        "concurrency": concurrency,
        "completed": counters["completed"],
        "errors": counters["errors"],
        "wall_s": wall,
        "throughput_rps": counters["completed"] / wall if wall else 0.0,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "p99_ms": _percentile(latencies, 99),
    }


def run_level(url, payload, concurrency, duration_s, warmup_s=0.0) -> dict[str, Any]:
    return asyncio.run(_run_level_async(url, payload, concurrency, duration_s, warmup_s))


def run_sweep(url, payload, concurrencies, duration_s, warmup_s=2.0) -> list[dict[str, Any]]:
    return [run_level(url, payload, c, duration_s, warmup_s) for c in concurrencies]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_driver.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add harness/loadtest/driver.py harness/loadtest/tests/test_driver.py
git commit -m "feat(loadtest): closed-loop async load driver with percentile latency"
```

---

### Task 4: Metrics aggregator (the five win-metrics)

**Files:**
- Create: `harness/loadtest/aggregate.py`
- Test: `harness/loadtest/tests/test_aggregate.py`

Given a framework's per-level driver records and per-level sampler summaries (plus idle RSS), compute the five metrics from spec §6.

- [ ] **Step 1: Write the failing test**

Create `harness/loadtest/tests/test_aggregate.py`:

```python
from harness.loadtest.aggregate import compute_metrics


def test_compute_metrics():
    levels = [
        {"concurrency": 1, "throughput_rps": 1.6, "p95_ms": 620, "completed": 96,
         "errors": 0, "rss_mean_bytes": 60_000_000, "cpu_seconds": 0.5},
        {"concurrency": 4, "throughput_rps": 6.2, "p95_ms": 650, "completed": 372,
         "errors": 0, "rss_mean_bytes": 72_000_000, "cpu_seconds": 1.8},
        {"concurrency": 16, "throughput_rps": 9.0, "p95_ms": 1700, "completed": 540,
         "errors": 3, "rss_mean_bytes": 120_000_000, "cpu_seconds": 6.0},
    ]
    m = compute_metrics(levels, idle_rss_bytes=50_000_000)
    assert m["throughput_ceiling_rps"] == 9.0
    # useful concurrency: largest C with p95 <= 2*baseline(620)=1240 -> C=4
    assert m["useful_concurrency"] == 4
    # rss/session at C=16: (120M-50M)/16
    assert abs(m["rss_per_session_bytes"]["16"] - (70_000_000 / 16)) < 1
    # cpu/request at C=16: 6.0/540
    assert abs(m["cpu_per_request_s"]["16"] - (6.0 / 540)) < 1e-6
    assert m["saturation_concurrency"] == 16  # first level with errors>0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_aggregate.py -v`
Expected: FAIL — `ModuleNotFoundError: harness.loadtest.aggregate`.

- [ ] **Step 3: Implement the aggregator**

Create `harness/loadtest/aggregate.py`:

```python
"""Compute the five concurrency win-metrics (spec §6) from per-level records.

Each input level dict must carry: concurrency, throughput_rps, p95_ms, completed,
errors, rss_mean_bytes, cpu_seconds. `idle_rss_bytes` is the server's RSS before
load (subtracted to get marginal RAM-per-session).
"""
from __future__ import annotations

from typing import Any


def compute_metrics(levels: list[dict[str, Any]], idle_rss_bytes: float) -> dict[str, Any]:
    if not levels:
        return {}
    levels = sorted(levels, key=lambda d: d["concurrency"])
    baseline_p95 = levels[0]["p95_ms"]

    throughput_ceiling = max(l["throughput_rps"] for l in levels)

    useful = levels[0]["concurrency"]
    for l in levels:
        if l["p95_ms"] <= 2.0 * baseline_p95:
            useful = l["concurrency"]

    rss_per_session = {}
    cpu_per_request = {}
    for l in levels:
        c = l["concurrency"]
        marginal = max(0.0, l["rss_mean_bytes"] - idle_rss_bytes)
        rss_per_session[str(c)] = marginal / c
        cpu_per_request[str(c)] = (l["cpu_seconds"] / l["completed"]) if l["completed"] else None

    saturation = None
    for l in levels:
        if l["errors"] > 0:
            saturation = l["concurrency"]
            break

    return {
        "throughput_ceiling_rps": throughput_ceiling,
        "useful_concurrency": useful,
        "rss_per_session_bytes": rss_per_session,
        "cpu_per_request_s": cpu_per_request,
        "saturation_concurrency": saturation,
        "baseline_p95_ms": baseline_p95,
        "levels": levels,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv-bench/bin/python -m pytest harness/loadtest/tests/test_aggregate.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add harness/loadtest/aggregate.py harness/loadtest/tests/test_aggregate.py
git commit -m "feat(loadtest): five-metric concurrency aggregator"
```

---

### Task 5: Colmena minimal load-test graph + boot smoke

**Files:**
- Create: `harness/loadtest/graphs/loadtest_minimal.json`

A Colmena DAG: `trigger_webhook` at `/run` → `llm_call` (provider `openai`, `base_url` = mock, one tool `run_sql` implemented as an `http_request` to the mock `/tool`). Schema is anchored on `colmena/tests/graphs/external/http_headers_dynamic.json` (a `llm_call` whose tool is `node_type: http_request`).

- [ ] **Step 1: Create the graph**

Create `harness/loadtest/graphs/loadtest_minimal.json`. Replace `${MOCK_BASE}` at run time (the orchestration script in Task 7 templates it):

```json
{
  "nodes": {
    "trigger": {
      "type": "trigger_webhook",
      "config": {
        "path": "/run",
        "method": "POST",
        "test_payload": { "prompt": "How many orders are there?" }
      }
    },
    "agent_llm": {
      "type": "llm_call",
      "config": {
        "provider": "openai",
        "model": "gemini-2.5-flash",
        "base_url": "${MOCK_BASE}/v1",
        "api_key": "sk-loadtest-mock",
        "stream": false,
        "temperature": 0.0,
        "system_message": "Answer the user's question. Use the run_sql tool exactly once, then report the count.",
        "tools": [
          {
            "name": "run_sql",
            "node_type": "http_request",
            "description": "Run a SQL query and return rows.",
            "config": {
              "url": "${MOCK_BASE}/tool",
              "method": "POST",
              "body_template": { "query": "{{query}}" }
            },
            "parameters": {
              "query": { "type": "string", "description": "SQL to execute" }
            }
          }
        ]
      }
    }
  },
  "edges": [{ "from": "trigger", "to": "agent_llm" }]
}
```

- [ ] **Step 2: Verify the graph schema against a real example**

Run: `.venv-bench/bin/python -c "import json; json.load(open('harness/loadtest/graphs/loadtest_minimal.json')); print('valid json')"`
Then compare field-for-field against `/Users/danielgarcia/startti/colmena/tests/graphs/external/http_headers_dynamic.json` (the `tools[].node_type=http_request` + `config.url`/`method`/`body_template`/`parameters` shape). **If the real example uses different key names** (e.g. `input_schema` instead of `parameters`, or `payload_template` instead of `body_template`), edit `loadtest_minimal.json` to match the real schema exactly — the engine validates on load.
Expected: `valid json`, and keys matching the reference graph.

- [ ] **Step 3: Boot smoke (manual, requires the Rust binary)**

The Colmena `serve` binary is `dag_engine` (built in the colmena repo). Start the mock and serve the graph, then hit `/run` once. Use the env from prior demos (`SECURE_VALUES_KEY`, `COLMENA_DATABASE_URL` re-exported as `DATABASE_URL`; see `colmena-dag-execution` memory).

```bash
# terminal A: mock
.venv-bench/bin/python -m harness.loadtest.stub_llm --port 9100 --delay-ms 50 &
# template the graph
MOCK_BASE=http://127.0.0.1:9100 .venv-bench/bin/python - <<'PY'
import os, pathlib
t = pathlib.Path("harness/loadtest/graphs/loadtest_minimal.json").read_text()
pathlib.Path("/tmp/loadtest_minimal.rendered.json").write_text(
    t.replace("${MOCK_BASE}", os.environ["MOCK_BASE"]))
print("rendered")
PY
# terminal B: serve (adjust path to the built dag_engine binary)
cd /Users/danielgarcia/startti/colmena && set -a && source /Users/danielgarcia/startti/colmena-bench/.env && set +a && \
  export DATABASE_URL="$COLMENA_DATABASE_URL" && \
  cargo run --release --bin dag_engine -- serve /tmp/loadtest_minimal.rendered.json --host 127.0.0.1 --port 3000
# terminal C: one request
curl -s -X POST http://127.0.0.1:3000/run -H 'content-type: application/json' \
  -d '{"prompt":"How many orders are there?"}'
```

Expected: a JSON response whose content includes the final answer (mock returns "There are 1000 orders."). If `serve` reports "No 'trigger_webhook' nodes found", the `path`/`type` keys are wrong — fix to match the reference graph. **Record whether the boot succeeded** — this is the first half of the Phase-1 go/no-go (Serve runs the workload at all).

- [ ] **Step 4: Commit**

```bash
git add harness/loadtest/graphs/loadtest_minimal.json
git commit -m "feat(loadtest): minimal Colmena DAG (webhook -> llm -> http tool -> llm)"
```

---

### Task 6: LangGraph warm FastAPI server

**Files:**
- Create: `runners/langgraph/server/__init__.py`
- Create: `runners/langgraph/server/app.py`

A long-running FastAPI server holding a pre-built `create_react_agent` (one `run_sql` tool that POSTs to the mock `/tool`) and a warm httpx client. `POST /run` runs the agent once and returns the answer. This mirrors the production deployment we hold Colmena's `Serve` to (spec §2 fairness rule 1).

- [ ] **Step 1: Implement the server**

Create `runners/langgraph/server/__init__.py` (empty) and `runners/langgraph/server/app.py`:

```python
"""LangGraph warm server for the concurrency load-test.

Production-style deployment: one long-running uvicorn process with a pre-built
agent and a warm httpx client. The single tool `run_sql` POSTs to the mock's
/tool endpoint, matching the Colmena graph's http_request tool so the work is
identical across frameworks.
"""
from __future__ import annotations

import argparse
import os

import httpx
from fastapi import FastAPI
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, create_model

_MOCK_BASE = os.environ.get("LOADTEST_MOCK_BASE", "http://127.0.0.1:9100")
_MODEL = os.environ.get("LOADTEST_MODEL", "gemini-2.5-flash")
_SYSTEM = ("Answer the user's question. Use the run_sql tool exactly once, "
           "then report the count.")


def build_app() -> FastAPI:
    app = FastAPI()
    # warm, shared client reused across requests
    client = httpx.Client(base_url=_MOCK_BASE, timeout=30.0)

    def _run_sql(query: str) -> str:
        return client.post("/tool", json={"query": query}).json()["result"]

    args_model = create_model("run_sql_Args", query=(str, ...))
    tool = StructuredTool.from_function(
        func=_run_sql, name="run_sql",
        description="Run a SQL query and return rows.", args_schema=args_model)

    llm = ChatOpenAI(
        model=_MODEL, base_url=f"{_MOCK_BASE}/v1", api_key="sk-loadtest-mock",
        temperature=0.0)
    agent = create_react_agent(llm, [tool])

    class RunRequest(BaseModel):
        prompt: str = "How many orders are there?"

    @app.post("/run")
    def run(req: RunRequest) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        out = agent.invoke({"messages": [SystemMessage(_SYSTEM), HumanMessage(req.prompt)]})
        last = out["messages"][-1]
        return {"answer": getattr(last, "content", str(last))}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9001)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke the server end-to-end against the mock**

```bash
.venv-bench/bin/python -m harness.loadtest.stub_llm --port 9100 --delay-ms 50 &
LOADTEST_MOCK_BASE=http://127.0.0.1:9100 \
  runners/langgraph/.venv/bin/python -m runner.server.app --port 9001 &
sleep 3
curl -s -X POST http://127.0.0.1:9001/run -H 'content-type: application/json' \
  -d '{"prompt":"How many orders are there?"}'
```

Note: run with the **langgraph runner's own venv** (`runners/langgraph/.venv`) so the framework deps resolve; ensure `fastapi`+`uvicorn`+`httpx` are installed there (`runners/langgraph/.venv/bin/pip install fastapi uvicorn`). The `-m runner.server.app` form requires running from `runners/langgraph/` or adding it to `PYTHONPATH`; if import fails, run `cd runners/langgraph && .venv/bin/python -m runner.server.app --port 9001`.
Expected: `{"answer":"There are 1000 orders."}` (the agent fired the tool once and reported the mock's final text).

- [ ] **Step 3: Commit**

```bash
git add runners/langgraph/server/__init__.py runners/langgraph/server/app.py
git commit -m "feat(loadtest): langgraph warm FastAPI server (one tool -> mock)"
```

---

### Task 7: Calibration + Phase-1 orchestration script

**Files:**
- Create: `harness/loadtest/calibrate.py`
- Create: `harness/loadtest/run_phase1.sh`

Calibrate the mock delay to real Gemini 2.5 Flash once, then run the sweep (sampler + driver) against Colmena `Serve` and the LangGraph server, writing per-framework JSON.

- [ ] **Step 1: Implement calibration**

Create `harness/loadtest/calibrate.py`:

```python
"""One-time calibration: measure real Gemini 2.5 Flash per-call latency through
the proxy and write the p50 to runs/demo13/calibration.json. The load sweep
itself never calls a real model — this only sets the mock's fixed delay so the
numbers are representative.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import time

import httpx

N = 20
PROXY = os.environ.get("PROXY_BASE_URL", "http://127.0.0.1:4000")
KEY = os.environ.get("LITELLM_PROXY_API_KEY", os.environ.get("LITELLM_MASTER_KEY", ""))
MODEL = os.environ.get("LOADTEST_MODEL", "gemini-2.5-flash")


def main() -> None:
    latencies = []
    with httpx.Client(timeout=60.0) as c:
        for i in range(N):
            t0 = time.monotonic()
            r = c.post(f"{PROXY}/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"},
                       json={"model": MODEL, "temperature": 0.0,
                             "messages": [{"role": "user", "content": "Reply with the single word OK."}]})
            r.raise_for_status()
            latencies.append((time.monotonic() - t0) * 1000.0)
    out = {
        "model": MODEL, "n": N,
        "p50_ms": round(statistics.median(latencies), 1),
        "mean_ms": round(statistics.fmean(latencies), 1),
        "min_ms": round(min(latencies), 1), "max_ms": round(max(latencies), 1),
    }
    path = pathlib.Path("runs/demo13/calibration.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement the orchestration script**

Create `harness/loadtest/run_phase1.sh`:

```bash
#!/usr/bin/env bash
# Phase-1 go/no-go sweep: Colmena Serve + LangGraph warm server vs the mock.
# Calibration is optional; if runs/demo13/calibration.json is absent we use a
# default delay. The sweep itself spends NO tokens.
set -euo pipefail
cd "$(dirname "$0")/../.."

MOCK_PORT=9100
COLMENA_PORT=3000
LANGGRAPH_PORT=9001
DELAY_MS="${DELAY_MS:-}"
CONCURRENCIES="${CONCURRENCIES:-1,2,4,8,16,32,64}"
DURATION_S="${DURATION_S:-30}"
OUT=runs/demo13/phase1
mkdir -p "$OUT"

# 1. delay: from calibration if present, else default 600ms
if [ -z "$DELAY_MS" ]; then
  if [ -f runs/demo13/calibration.json ]; then
    DELAY_MS=$(.venv-bench/bin/python -c "import json;print(int(json.load(open('runs/demo13/calibration.json'))['p50_ms']))")
  else
    DELAY_MS=600
  fi
fi
echo "Using mock delay ${DELAY_MS}ms; concurrencies ${CONCURRENCIES}"

# 2. start mock
.venv-bench/bin/python -m harness.loadtest.stub_llm --port "$MOCK_PORT" --delay-ms "$DELAY_MS" &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null || true' EXIT
sleep 2

# 3. render colmena graph
MOCK_BASE="http://127.0.0.1:${MOCK_PORT}" .venv-bench/bin/python - <<'PY'
import os, pathlib
t = pathlib.Path("harness/loadtest/graphs/loadtest_minimal.json").read_text()
pathlib.Path("/tmp/loadtest_minimal.rendered.json").write_text(t.replace("${MOCK_BASE}", os.environ["MOCK_BASE"]))
PY

# 4. drive each framework (the python runner does start/sample/stop/drive per server)
.venv-bench/bin/python -m harness.loadtest.run_phase1_drive \
  --mock-base "http://127.0.0.1:${MOCK_PORT}" \
  --colmena-port "$COLMENA_PORT" \
  --langgraph-port "$LANGGRAPH_PORT" \
  --concurrencies "$CONCURRENCIES" \
  --duration-s "$DURATION_S" \
  --out "$OUT"

echo "Phase-1 sweep complete -> $OUT"
```

- [ ] **Step 3: Implement the per-server drive module**

Create `harness/loadtest/run_phase1_drive.py` — starts each server as a subprocess, samples it, drives the sweep, tears it down. (Colmena: the prebuilt `dag_engine` binary; LangGraph: the runner venv.)

```python
"""Start each server, sample its process tree, run the concurrency sweep, write
per-framework results. Colmena Serve and the LangGraph server are each started
as subprocesses so the sampler can watch the whole tree.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import time

import httpx

from harness.loadtest import driver
from harness.loadtest.aggregate import compute_metrics
from harness.loadtest.sampler import ResourceSampler

COLMENA_REPO = os.environ.get("COLMENA_REPO", "/Users/danielgarcia/startti/colmena")
COLMENA_BIN = os.environ.get(
    "COLMENA_DAG_ENGINE_BIN", f"{COLMENA_REPO}/target/release/dag_engine")
LANGGRAPH_DIR = "runners/langgraph"
LANGGRAPH_PY = f"{LANGGRAPH_DIR}/.venv/bin/python"


def _wait_health(url: str, timeout_s: float = 30.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        try:
            if httpx.get(url, timeout=2.0).status_code < 500:
                return True
        except Exception:
            time.sleep(0.3)
    return False


def _idle_rss(pid: int) -> float:
    s = ResourceSampler(pid=pid, interval=0.05)
    s.start()
    time.sleep(1.0)
    s.stop()
    return s.summarize()["rss_mean_bytes"]


def _drive_server(name, proc, run_url, health_url, concurrencies, duration_s, payload):
    assert _wait_health(health_url), f"{name} did not become healthy"
    idle = _idle_rss(proc.pid)
    levels = []
    for c in concurrencies:
        sampler = ResourceSampler(pid=proc.pid, interval=0.1)
        sampler.start()
        rec = driver.run_level(run_url, payload, c, duration_s, warmup_s=2.0)
        sampler.stop()
        summ = sampler.summarize()
        rec.update(rss_mean_bytes=summ["rss_mean_bytes"],
                   rss_peak_bytes=summ["rss_peak_bytes"],
                   rss_auc_bytes_s=summ["rss_auc_bytes_s"],
                   cpu_seconds=summ["cpu_seconds"])
        levels.append(rec)
        print(f"[{name}] C={c} thr={rec['throughput_rps']:.1f} p95={rec['p95_ms']:.0f}ms "
              f"rss={summ['rss_mean_bytes']/1e6:.0f}MB err={rec['errors']}")
    return {"framework": name, "idle_rss_bytes": idle, "levels": levels,
            "metrics": compute_metrics(levels, idle)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock-base", required=True)
    ap.add_argument("--colmena-port", type=int, required=True)
    ap.add_argument("--langgraph-port", type=int, required=True)
    ap.add_argument("--concurrencies", required=True)
    ap.add_argument("--duration-s", type=float, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    concs = [int(x) for x in a.concurrencies.split(",")]
    payload = {"prompt": "How many orders are there?"}
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # --- Colmena Serve ---
    cenv = dict(os.environ)
    cenv["DATABASE_URL"] = os.environ.get("COLMENA_DATABASE_URL", "")
    colmena = subprocess.Popen(
        [COLMENA_BIN, "serve", "/tmp/loadtest_minimal.rendered.json",
         "--host", "127.0.0.1", "--port", str(a.colmena_port)],
        cwd=COLMENA_REPO, env=cenv)
    try:
        res = _drive_server(
            "colmena", colmena,
            f"http://127.0.0.1:{a.colmena_port}/run",
            f"http://127.0.0.1:{a.colmena_port}/run",  # no /health on serve; health via /run 200
            concs, a.duration_s, payload)
        (out / "colmena.json").write_text(json.dumps(res, indent=2))
    finally:
        colmena.terminate()
        colmena.wait(timeout=10)

    # --- LangGraph warm server ---
    lenv = dict(os.environ)
    lenv["LOADTEST_MOCK_BASE"] = a.mock_base
    langgraph = subprocess.Popen(
        [LANGGRAPH_PY, "-m", "runner.server.app", "--port", str(a.langgraph_port)],
        cwd=LANGGRAPH_DIR, env=lenv)
    try:
        res = _drive_server(
            "langgraph", langgraph,
            f"http://127.0.0.1:{a.langgraph_port}/run",
            f"http://127.0.0.1:{a.langgraph_port}/health",
            concs, a.duration_s, payload)
        (out / "langgraph.json").write_text(json.dumps(res, indent=2))
    finally:
        langgraph.terminate()
        langgraph.wait(timeout=10)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Make the script executable and dry-run the drive module's import**

Run:
```bash
chmod +x harness/loadtest/run_phase1.sh
.venv-bench/bin/python -c "import harness.loadtest.run_phase1_drive, harness.loadtest.calibrate; print('imports ok')"
```
Expected: `imports ok`.

- [ ] **Step 5: Commit**

```bash
git add harness/loadtest/calibrate.py harness/loadtest/run_phase1.sh harness/loadtest/run_phase1_drive.py
git commit -m "feat(loadtest): calibration + phase-1 orchestration (serve vs langgraph sweep)"
```

---

### Task 8: Phase-1 verdict — verify Serve concurrency + win/null

**Files:**
- Create: `harness/loadtest/phase1_verdict.py`
- Create: `runs/demo13/phase1/VERDICT.md` (generated)

The go/no-go. Two questions: (1) **Is `Serve` actually concurrent?** With mock delay `D`, a serialized server caps throughput near `1000/D` rps regardless of `C`; a concurrent server scales toward `C*1000/D` until it saturates. (2) **Does Colmena win** on the §6 metrics vs LangGraph?

- [ ] **Step 1: Implement the verdict analyzer**

Create `harness/loadtest/phase1_verdict.py`:

```python
"""Phase-1 go/no-go. Reads runs/demo13/phase1/{colmena,langgraph}.json and decides:
  (A) Is Colmena Serve concurrent? (throughput must rise with C, not flatline at ~1/D)
  (B) Does Colmena win on RAM/session, CPU/request, throughput ceiling, saturation?
Writes VERDICT.md. Exit code 0 = GO, 1 = NO-GO/regression (so CI/scripts can gate).
"""
from __future__ import annotations

import json
import pathlib
import sys

PHASE1 = pathlib.Path("runs/demo13/phase1")


def _load(name):
    return json.loads((PHASE1 / f"{name}.json").read_text())


def _scales_with_concurrency(levels) -> tuple[bool, float]:
    levels = sorted(levels, key=lambda d: d["concurrency"])
    t1 = next(l["throughput_rps"] for l in levels if l["concurrency"] == levels[0]["concurrency"])
    tmax = max(l["throughput_rps"] for l in levels)
    ratio = (tmax / t1) if t1 else 0.0
    # concurrent runtime should at least ~triple throughput from C=1 to its ceiling
    return ratio >= 3.0, ratio


def main() -> None:
    colmena = _load("colmena")
    langgraph = _load("langgraph")
    c_scales, c_ratio = _scales_with_concurrency(colmena["levels"])
    cm, lm = colmena["metrics"], langgraph["metrics"]

    def _min_rss_session(m):
        vals = [v for v in m["rss_per_session_bytes"].values()]
        return min(vals) if vals else float("inf")

    wins = {
        "throughput_ceiling": cm["throughput_ceiling_rps"] >= lm["throughput_ceiling_rps"],
        "rss_per_session": _min_rss_session(cm) <= _min_rss_session(lm),
        "useful_concurrency": cm["useful_concurrency"] >= lm["useful_concurrency"],
    }
    go = c_scales and (sum(wins.values()) >= 2)

    lines = [
        "# demo13 — Phase-1 verdict", "",
        f"**Serve concurrent?** {'YES' if c_scales else 'NO'} "
        f"(throughput C=1→ceiling ×{c_ratio:.1f}; need ≥3.0)", "",
        "## §6 metrics (colmena vs langgraph)", "",
        f"- throughput ceiling: {cm['throughput_ceiling_rps']:.1f} vs "
        f"{lm['throughput_ceiling_rps']:.1f} rps — colmena {'wins' if wins['throughput_ceiling'] else 'loses'}",
        f"- min RAM/session: {_min_rss_session(cm)/1e6:.1f} vs {_min_rss_session(lm)/1e6:.1f} MB "
        f"— colmena {'wins' if wins['rss_per_session'] else 'loses'}",
        f"- useful concurrency: {cm['useful_concurrency']} vs {lm['useful_concurrency']} "
        f"— colmena {'wins' if wins['useful_concurrency'] else 'loses'}", "",
        f"## Verdict: {'GO ✅' if go else 'NO-GO ❌'}", "",
        "GO ⇒ build the other 4 servers (Phase 2). NO-GO ⇒ record the null result "
        "honestly and stop, as with demos 11/12.",
    ]
    path = PHASE1 / "VERDICT.md"
    path.write_text("\n".join(lines))
    print("\n".join(lines))
    sys.exit(0 if go else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full Phase-1 sweep + verdict**

This is the real measurement. Requires: proxy not needed for the sweep; the `dag_engine` release binary built (`cd /Users/danielgarcia/startti/colmena && cargo build --release --bin dag_engine`); the bench `.env` sourced for `COLMENA_DATABASE_URL`/`SECURE_VALUES_KEY`; `fastapi uvicorn` installed in `runners/langgraph/.venv`.

```bash
# optional one-time calibration (spends ~cents); skip to use default 600ms:
# .venv-bench/bin/python -m harness.loadtest.calibrate
set -a && source .env && set +a
DURATION_S=20 CONCURRENCIES=1,2,4,8,16,32,64 bash harness/loadtest/run_phase1.sh
.venv-bench/bin/python -m harness.loadtest.phase1_verdict || echo "NO-GO (exit 1)"
```

Expected: `runs/demo13/phase1/colmena.json`, `langgraph.json`, and `VERDICT.md`. Read `VERDICT.md`. **The "Serve concurrent?" line is the load-bearing result** — if NO, Colmena's HTTP layer is serializing despite axum (e.g. a global lock in `Arc<ColmenaEngine>`); investigate `dag_engine/api.rs` `handler_webhook` + the engine's shared state before any Phase-2 work.

- [ ] **Step 3: Commit code + results**

```bash
git add harness/loadtest/phase1_verdict.py
git add runs/demo13/phase1/colmena.json runs/demo13/phase1/langgraph.json runs/demo13/phase1/VERDICT.md
[ -f runs/demo13/calibration.json ] && git add runs/demo13/calibration.json
git commit -m "feat(loadtest): phase-1 verdict analyzer + recorded go/no-go results"
```

- [ ] **Step 4: Decision gate (STOP here and report to the human)**

Do **not** proceed to Phase 2 automatically. Present `VERDICT.md` to the human with a recommendation:
- **GO:** Serve is concurrent and Colmena wins ≥2 of 3 gate metrics → proceed to a Phase-2 detailed plan (the other 4 servers + DB-backed `run_sql` variant + full plots).
- **NO-GO:** record the null result in `docs/demos/demo13-concurrency.md` honestly and add a one-line note to the whitepaper honesty section; do not build the other servers.

---

## Phase 2 & 3 (outline — detailed plan written only after a GO verdict)

**Phase 2 — full field.** For each of CrewAI, LangChain, LlamaIndex, Google ADK: add `runners/<fw>/server/app.py` mirroring Task 6's warm-server pattern with that framework's idiomatic one-tool agent; register it in `run_phase1_drive.py` (generalize to an N-server loop). Add the DB-backed `run_sql` variant (asyncpg pool for Python; Colmena `sql` node) as a second workload to exercise the warm-pool dimension, documented as deployment-not-framework per spec §2 rule 2.

**Phase 3 — report.** Final sweep across all 6; generate charts (throughput-vs-C, p99-vs-C, RAM-over-time, RAM-per-session-vs-C, CPU-per-request) into `runs/demo13/plots/`; write `docs/demos/demo13-concurrency.md` leading with the spec §2 honesty framing (no parallelism claim; warm-pool not a framework win); if the win is clean, add one chart to the whitepaper/brief.

---

## Self-Review

**Spec coverage:** §2 honesty frame → Task 5/8 (Serve-concurrency verification) + verdict's no-parallelism framing; §2 fairness rule 1 (prod-vs-prod) → Task 6 warm server; §3 mock → Task 1 + calibrate (Task 7); §4 workload → Task 5 graph + Task 6 tool (Phase-1 deviation to constant tool documented at top, allowed by §8.4); §5 components → Tasks 1–4, 6, 7; §6 five metrics → Task 4 + verdict Task 8; §7 phasing → plan scoped to Phase 1 + outline; §8 risks → Task 5 (schema), Task 8 (Serve concurrency), idle-RSS subtraction (Task 4/7 `idle_rss`). **Gap accepted:** DB/warm-pool (§4, §8.4) deferred to Phase 2 by explicit Phase-1 deviation. **Out-of-scope (§9):** no real-LLM sweep, no Pro, no parallelism claim — honored.

**Placeholder scan:** none — every code step has complete code; `${MOCK_BASE}` is a documented runtime template with a concrete render step (Task 5 Step 3, Task 7 Step 2).

**Type consistency:** `compute_metrics(levels, idle_rss_bytes)` keys (`throughput_ceiling_rps`, `useful_concurrency`, `rss_per_session_bytes`, `cpu_per_request_s`, `saturation_concurrency`) are consistent across Task 4 and Task 8; driver record keys (`concurrency`, `completed`, `errors`, `throughput_rps`, `p50_ms`, `p95_ms`, `p99_ms`) consistent across Tasks 3, 7, 8; sampler `summarize()` keys (`rss_mean_bytes`, `rss_peak_bytes`, `rss_auc_bytes_s`, `cpu_seconds`) consistent across Tasks 2, 7. Mock tool name `run_sql` consistent across Tasks 1, 5, 6.
