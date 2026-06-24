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
