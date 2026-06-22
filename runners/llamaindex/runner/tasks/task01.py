"""Task 1 — hello world, on LlamaIndex."""
from __future__ import annotations

from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole

from bench_common import RunnerArgs


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    messages = [ChatMessage(role=MessageRole.USER, content=task_def["prompt"])]
    resp = llm.chat(messages)
    answer = resp.message.content if hasattr(resp, "message") else str(resp)

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    raw = getattr(resp, "raw", None)
    raw_usage = None
    if isinstance(raw, dict):
        raw_usage = raw.get("usage")
    elif raw is not None:
        raw_usage = getattr(raw, "usage", None)
    if raw_usage is not None:
        get = raw_usage.get if isinstance(raw_usage, dict) else lambda k, d=0: getattr(raw_usage, k, d)
        usage["input"] = int(get("prompt_tokens", 0) or 0)
        usage["output"] = int(get("completion_tokens", 0) or 0)
    return answer, usage
