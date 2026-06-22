"""Aggregate N run-output.json files into one aggregated.json.

Skeleton for T08; CI plumbing + bootstrap method land in T18. The math here
is good enough to validate the schema contract today.
"""
from __future__ import annotations

import json
import random
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

HARNESS_DIR = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = HARNESS_DIR / "schemas"
RUN_OUTPUT_SCHEMA = json.loads((SCHEMAS_DIR / "run_output.schema.json").read_text())
AGGREGATED_SCHEMA = json.loads((SCHEMAS_DIR / "aggregated.schema.json").read_text())

_VALIDATOR = Draft202012Validator(RUN_OUTPUT_SCHEMA)


def _stat(values: Sequence[float], *, ci_iters: int = 5000, seed: int = 42) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0}
    sorted_vals = sorted(values)
    out: dict[str, float] = {
        "mean": float(statistics.fmean(values)),
        "stdev": float(statistics.pstdev(values)) if len(values) > 1 else 0.0,
        "p50": float(_quantile(sorted_vals, 0.50)),
        "p95": float(_quantile(sorted_vals, 0.95)),
        "p99": float(_quantile(sorted_vals, 0.99)),
        "min": float(sorted_vals[0]),
        "max": float(sorted_vals[-1]),
    }
    # Bootstrap basic CI for the mean. Good enough for the contract; T18
    # may swap in BCa.
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(ci_iters):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(sample))
    means.sort()
    out["ci95_low"] = float(_quantile(means, 0.025))
    out["ci95_high"] = float(_quantile(means, 0.975))
    return out


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return float(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac)


def aggregate(run_dir: Path, *, pricing_table_date: str | None = None) -> dict[str, Any]:
    """Aggregate every *.json under `run_dir` into one aggregated dict."""
    runs: list[dict] = []
    for path in sorted(run_dir.glob("*.json")):
        data = json.loads(path.read_text())
        _VALIDATOR.validate(data)
        runs.append(data)

    if not runs:
        raise ValueError(f"no runs found in {run_dir}")

    first = runs[0]
    n_failed = sum(1 for r in runs if not r["success"]["ok"])
    success_rate = (len(runs) - n_failed) / len(runs)

    latencies = [r["latency_ms"] for r in runs]
    tokens_in = [r["tokens"]["input"] for r in runs]
    tokens_out = [r["tokens"]["output"] for r in runs]
    tokens_cached = [r["tokens"].get("cached", 0) for r in runs]
    tool_calls = [r.get("tool_calls", 0) for r in runs]

    agg: dict[str, Any] = {
        "task_id": first["task_id"],
        "variant": first["variant"],
        "framework": first["framework"],
        "framework_version": first.get("framework_version", ""),
        "model_alias": first["model_alias"],
        "n": len(runs),
        "n_failed": n_failed,
        "success_rate": success_rate,
        "stats": {
            "latency_ms": _stat(latencies),
            "tokens_input": _stat(tokens_in),
            "tokens_output": _stat(tokens_out),
            "tokens_cached": _stat(tokens_cached),
            "tool_calls": _stat(tool_calls),
        },
        "cost": {
            # Real USD pricing computed at report-time (T18) using pricing_table.json.
            # Skeleton here just zeros it out.
            "usd_per_run": _stat([0.0 for _ in runs]),
            "pricing_table_date": pricing_table_date or "1970-01-01",
        },
    }
    Draft202012Validator(AGGREGATED_SCHEMA).validate(agg)
    return agg


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    agg = aggregate(args.run_dir)
    text = json.dumps(agg, indent=2)
    if args.out:
        args.out.write_text(text)
    else:
        print(text)
