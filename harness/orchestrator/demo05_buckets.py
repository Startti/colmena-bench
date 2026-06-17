"""Bucket proxy spans into conversation turns by wall-clock timestamp.

Colmena cannot forward a per-call header, so we attribute each span to a turn by
comparing its ts_start to the runner-emitted turn-boundary timestamps. Works
identically for every framework.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _to_epoch(ts: Any) -> float:
    """Accept an ISO-8601 string (…Z) or an epoch float; return epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def bucket_spans_by_turn(spans: list[dict], boundaries: list[str]) -> dict:
    """Sum span tokens into turns delimited by `boundaries`.

    boundaries has length n_turns + 1: turn k = [boundaries[k], boundaries[k+1]).
    A span at/after the last boundary is attributed to the last turn (handles
    clock skew on the final emit).
    """
    edges = [_to_epoch(b) for b in boundaries]
    n_turns = max(0, len(edges) - 1)
    per_in = [0 for _ in range(n_turns)]
    per_out = [0 for _ in range(n_turns)]
    per_cached = [0 for _ in range(n_turns)]
    per_lat = [0.0 for _ in range(n_turns)]    # summed provider latency_ms of calls in the turn
    per_calls = [0 for _ in range(n_turns)]    # number of LLM calls in the turn
    per_ttft = [None for _ in range(n_turns)]  # first call's ttft_ms in the turn
    for sp in spans:
        t = _to_epoch(sp.get("ts_start", 0))
        idx = 0
        while idx < n_turns - 1 and t >= edges[idx + 1]:
            idx += 1
        per_in[idx] += int(sp.get("tokens_input", 0))
        per_out[idx] += int(sp.get("tokens_output", 0))
        per_cached[idx] += int(sp.get("tokens_cached", 0) or 0)
        per_lat[idx] += float(sp.get("latency_ms", 0) or 0)
        per_calls[idx] += 1
        if per_ttft[idx] is None and sp.get("ttft_ms"):
            per_ttft[idx] = sp.get("ttft_ms")
    cum, running = [], 0
    for v in per_in:
        running += v
        cum.append(running)
    return {
        "per_turn_input": per_in,
        "per_turn_output": per_out,
        "cumulative_input": cum,
        # richer per-turn metrics (additive; existing keys unchanged)
        "per_turn_cached": per_cached,
        "per_turn_latency_ms": per_lat,
        "per_turn_calls": per_calls,
        "per_turn_ttft_ms": per_ttft,
        "total_calls": sum(per_calls),
        "total_latency_ms": sum(per_lat),
    }
