"""Compose a comparative markdown report from several aggregated.json files.

Skeleton for T08. PNG/SVG chart generation lands in T18/T26.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def _row(agg: dict) -> str:
    stats = agg["stats"]
    return (
        f"| {agg['framework']:<11} "
        f"| {agg['n']:>3} "
        f"| {stats['latency_ms']['p50']:>10.1f} "
        f"| {stats['latency_ms']['p95']:>10.1f} "
        f"| {stats['tokens_input']['mean']:>10.1f} "
        f"| {stats['tokens_output']['mean']:>11.1f} "
        f"| {agg['success_rate'] * 100:>5.1f}% |"
    )


def render(aggregated: Iterable[dict]) -> str:
    aggregated = list(aggregated)
    if not aggregated:
        return "_No data._"
    first = aggregated[0]
    lines = [
        f"# Report: task `{first['task_id']}` variant `{first['variant']}`",
        "",
        f"Model: `{first['model_alias']}` — N={first['n']} per framework.",
        "",
        "| Framework   |   N | p50 latency (ms) | p95 latency (ms) | mean tokens in | mean tokens out | success |",
        "|-------------|-----|-----------------:|-----------------:|---------------:|----------------:|--------:|",
    ]
    for agg in aggregated:
        lines.append(_row(agg))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("aggregated_jsons", nargs="+", type=Path)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    items = [json.loads(path.read_text()) for path in args.aggregated_jsons]
    md = render(items)
    if args.out:
        args.out.write_text(md)
    else:
        print(md)
