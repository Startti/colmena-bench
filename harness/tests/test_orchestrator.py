"""Unit tests for the orchestrator skeleton."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS_DIR))

from orchestrator.aggregate import aggregate  # noqa: E402
from orchestrator.report import render  # noqa: E402


def _make_run(out_dir: Path, *, framework="colmena", latency=1000, tokens_in=10, tokens_out=4, ok=True) -> Path:
    run = {
        "run_id": str(uuid.uuid4()),
        "task_id": "01_hello_world",
        "variant": "default",
        "framework": framework,
        "framework_version": "v0.1",
        "model_alias": "gemini-2.5-flash",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "latency_ms": latency,
        "tokens": {"input": tokens_in, "output": tokens_out, "cached": 0},
        "tool_calls": 0,
        "success": {"ok": ok},
        "answer": "hi",
        "host": {"hostname": "h", "os": "Linux", "cpu_model": "M2", "ram_gb": 16.0},
    }
    p = out_dir / f"{run['run_id']}.json"
    p.write_text(json.dumps(run))
    return p


def test_aggregate_handles_3_runs(tmp_path):
    for latency in (900, 1000, 1100):
        _make_run(tmp_path, latency=latency)
    agg = aggregate(tmp_path)
    assert agg["n"] == 3
    assert agg["success_rate"] == 1.0
    assert agg["stats"]["latency_ms"]["p50"] == 1000
    assert agg["stats"]["latency_ms"]["min"] == 900
    assert agg["stats"]["latency_ms"]["max"] == 1100
    # Bootstrap CI must be a non-degenerate interval around the mean.
    ci = agg["stats"]["latency_ms"]
    assert ci["ci95_low"] <= ci["mean"] <= ci["ci95_high"]


def test_aggregate_counts_failures(tmp_path):
    _make_run(tmp_path, ok=True)
    _make_run(tmp_path, ok=False)
    _make_run(tmp_path, ok=False)
    agg = aggregate(tmp_path)
    assert agg["n"] == 3
    assert agg["n_failed"] == 2
    assert agg["success_rate"] == pytest.approx(1 / 3)


def test_report_renders_for_one_framework(tmp_path):
    for latency in (900, 1000, 1100):
        _make_run(tmp_path, latency=latency)
    agg = aggregate(tmp_path)
    md = render([agg])
    assert "task `01_hello_world`" in md
    assert "colmena" in md
    assert "p50 latency" in md


def test_aggregate_rejects_empty_dir(tmp_path):
    with pytest.raises(ValueError):
        aggregate(tmp_path)
