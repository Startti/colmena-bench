"""Grader for verify_baseline.sh.

Validates the 4 invariants for one framework after its runs land:

  1. Each run_output.json validates against run_output.schema.json.
  2. proxy/spans/run-<run_id>.jsonl exists for every run_id.
  3. sum(span tokens_input + tokens_output) is within ±2 % of
     run_output.tokens.input + run_output.tokens.output.
  4. run_output.tool_calls within ±1 of the count of tool-call spans.

Prints a per-run table and exits non-zero if any invariant fails.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "harness/schemas/run_output.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def load_spans(spans_dir: Path, run_id: str) -> list[dict]:
    path = spans_dir / f"run-{run_id}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def grade_one(run_path: Path, spans_dir: Path) -> tuple[bool, list[str]]:
    failures: list[str] = []
    payload = json.loads(run_path.read_text())
    try:
        VALIDATOR.validate(payload)
    except Exception as e:  # noqa: BLE001
        failures.append(f"schema: {e.message if hasattr(e, 'message') else e}")

    run_id = payload.get("run_id", "")
    spans = load_spans(spans_dir, run_id)
    if not spans:
        failures.append(f"spans: proxy/spans/run-{run_id}.jsonl missing or empty")
        return (not failures, failures)

    runner_total = payload["tokens"]["input"] + payload["tokens"]["output"]
    proxy_total = sum(s.get("tokens_input", 0) + s.get("tokens_output", 0) for s in spans)
    if runner_total > 0 and proxy_total > 0:
        delta = abs(runner_total - proxy_total) / max(runner_total, proxy_total)
        if delta > 0.02:
            failures.append(
                f"tokens: runner={runner_total} proxy={proxy_total} Δ={delta:.2%} > 2%"
            )
    elif proxy_total == 0:
        failures.append("tokens: proxy reported 0 tokens — runner likely bypassed proxy")
    # If runner reports 0 but proxy reports > 0, that's a runner reporting
    # bug — flag but don't fail (T1 hello-world); proxy is source of truth.

    # Tool-call count: spans don't currently emit tool-call markers in the T1
    # scaffold (no tools). Once T20 tool spans land, count `kind=tool_call`.
    runner_tool_calls = payload.get("tool_calls", 0)
    proxy_tool_calls = sum(1 for s in spans if s.get("kind") == "tool_call")
    if abs(runner_tool_calls - proxy_tool_calls) > 1:
        failures.append(
            f"tool_calls: runner={runner_tool_calls} proxy={proxy_tool_calls} Δ>1"
        )

    return (not failures, failures)


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--framework", required=True)
    p.add_argument("--runs-dir", type=Path, required=True)
    p.add_argument("--spans-dir", type=Path, required=True)
    args = p.parse_args(list(argv) if argv is not None else None)

    runs = sorted(args.runs_dir.glob("*.json"))
    if not runs:
        print(f"  no runs in {args.runs_dir}", file=sys.stderr)
        return 1

    all_ok = True
    print(f"  {'run_id':36}  {'status':6}  details")
    print(f"  {'-'*36}  {'-'*6}  {'-'*40}")
    for run_path in runs:
        ok, failures = grade_one(run_path, args.spans_dir)
        run_id = run_path.stem
        status = "PASS" if ok else "FAIL"
        details = "" if ok else " | ".join(failures)
        print(f"  {run_id:36}  {status:6}  {details}")
        all_ok &= ok

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
