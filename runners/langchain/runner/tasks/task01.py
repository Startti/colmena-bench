"""Task 1 — hello world, on LangChain."""
from __future__ import annotations

from typing import Any

from bench_common import RunnerArgs


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    resp = llm.invoke(task_def["prompt"])
    answer = resp.content if hasattr(resp, "content") else str(resp)

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    meta = getattr(resp, "usage_metadata", None)
    if meta:
        usage["input"] = int(meta.get("input_tokens", 0) or 0)
        usage["output"] = int(meta.get("output_tokens", 0) or 0)
        details = meta.get("input_token_details") or {}
        usage["cached"] = int(details.get("cache_read", 0) or 0)
    return answer, usage
