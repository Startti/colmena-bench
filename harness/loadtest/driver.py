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
