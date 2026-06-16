"""Framework-agnostic runner core. See bench_common/__init__.py for usage.

This module has NO framework dependencies — only stdlib + pydantic-free
helpers (psutil, pyyaml), which every runner venv already pins. The
framework name and version are passed in by each runner so this code stays
shared across all six.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil
import yaml

MODEL_ALIASES = ["gemini-2.5-flash", "claude-haiku", "gpt-4o-mini"]


@dataclass
class RunnerArgs:
    task: Path
    variant: str
    run_id: str
    model_alias: str
    proxy_base_url: str
    output: Path
    timeout_seconds: int


def parse_args(framework_name: str, argv: list[str] | None = None) -> RunnerArgs:
    p = argparse.ArgumentParser(description=f"{framework_name} runner")
    p.add_argument("--task", required=True, type=Path)
    p.add_argument("--variant", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--model-alias", required=True, choices=MODEL_ALIASES)
    p.add_argument("--proxy-base-url", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--timeout-seconds", type=int, default=300)
    ns = p.parse_args(argv)
    return RunnerArgs(
        task=ns.task,
        variant=ns.variant,
        run_id=ns.run_id,
        model_alias=ns.model_alias,
        proxy_base_url=ns.proxy_base_url,
        output=ns.output,
        timeout_seconds=ns.timeout_seconds,
    )


def load_task(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def variant_params(task: dict, variant: str) -> dict:
    """Return the task's variant entry matching `variant`, or {} if absent."""
    for v in task.get("variants", []) or []:
        if v.get("name") == variant:
            return v
    return {}


def host_info() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu_model": platform.processor() or platform.machine(),
        "ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
    }


def score_success(spec: dict[str, Any], answer: Any) -> dict[str, Any]:
    """Apply the task's `success.kind` rule to the answer."""
    kind = spec.get("kind")
    if kind == "regex":
        text = answer if isinstance(answer, str) else json.dumps(answer)
        ok = re.search(spec["pattern"], text) is not None
        return {"ok": bool(ok)}
    if kind == "exact_numeric":
        try:
            val = float(str(answer).strip())
            target = float(spec["target"]) if "target" in spec else None
            tol = float(spec.get("tolerance", 0))
            ok = target is not None and abs(val - target) <= tol
            return {"ok": ok}
        except (TypeError, ValueError):
            return {"ok": False, "reason": "not numeric"}
    # llm_judge / set_equality land in later tasks.
    return {"ok": False, "reason": f"success kind {kind!r} not implemented in T1 scaffold"}


def emit_output(
    args: RunnerArgs,
    *,
    framework_name: str,
    framework_version: str,
    started_at: datetime,
    ended_at: datetime,
    cold_start_ms: int,
    answer: Any,
    tokens_input: int,
    tokens_output: int,
    tokens_cached: int,
    tool_calls: int,
    success: dict[str, Any],
    error: str | None = None,
    extras: dict[str, Any] | None = None,
) -> None:
    task = load_task(args.task)
    payload = {
        "run_id": args.run_id,
        "task_id": task["id"],
        "variant": args.variant,
        "framework": framework_name,
        "framework_version": framework_version,
        "model_alias": args.model_alias,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "ended_at": ended_at.isoformat().replace("+00:00", "Z"),
        "latency_ms": int((ended_at - started_at).total_seconds() * 1000),
        "cold_start_ms": cold_start_ms,
        "ttft_ms": None,  # Filled by orchestrator from proxy spans.
        "tokens": {
            "input": int(tokens_input),
            "output": int(tokens_output),
            "cached": int(tokens_cached),
        },
        "tool_calls": int(tool_calls),
        "ram_peak_mb": round(psutil.Process().memory_info().rss / (1024 ** 2), 2),
        "success": success,
        "answer": answer,
        "error": error,
        "host": host_info(),
        "extras": extras or {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, default=str))


TaskHandler = Callable[[dict[str, Any], Any, RunnerArgs], "tuple[Any, dict[str, int]]"]
"""Signature: (task_dict, llm, args) -> (answer, usage)

`usage` is an int dict with keys: input, output, cached, tool_calls.
"""


def run(
    framework_name: str,
    framework_version_fn: Callable[[], str],
    llm_factory: Callable[[RunnerArgs], Any],
    handlers: dict[str, TaskHandler],
) -> int:
    """Generic main: parse args, dispatch by task.id, time it, emit output."""
    t0_cold = time.perf_counter()
    args = parse_args(framework_name, sys.argv[1:])
    task = load_task(args.task)
    task_id = task["id"]
    if task_id not in handlers:
        sys.stderr.write(f"{framework_name} runner has no handler for task {task_id!r}\n")
        return 1
    cold_start_ms = int((time.perf_counter() - t0_cold) * 1000)

    llm = llm_factory(args)
    started = datetime.now(timezone.utc)
    answer: Any = None
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras: dict[str, Any] = {}
    error: str | None = None
    try:
        result = handlers[task_id](task, llm, args)
        if len(result) == 3:
            answer, usage, extras = result
        else:
            answer, usage = result
    except Exception as e:  # noqa: BLE001 — runner-level catch-all
        error = f"{type(e).__name__}: {e}"
    ended = datetime.now(timezone.utc)

    success = (
        score_success(task["success"], answer)
        if error is None
        else {"ok": False, "reason": error}
    )
    emit_output(
        args,
        framework_name=framework_name,
        framework_version=framework_version_fn(),
        started_at=started,
        ended_at=ended,
        cold_start_ms=cold_start_ms,
        answer=answer,
        tokens_input=usage.get("input", 0),
        tokens_output=usage.get("output", 0),
        tokens_cached=usage.get("cached", 0),
        tool_calls=usage.get("tool_calls", 0),
        success=success,
        error=error,
        extras=extras,
    )
    return 0
