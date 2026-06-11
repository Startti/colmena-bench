"""Task 1 — hello world, on Colmena.

Single LLM call via the native module's OpenAI adapter. Colmena's
`ColmenaLlm.call` returns only the answer string (no usage), so we report
zero tokens — the proxy span is the authoritative token source
(METHODOLOGY §4).
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

from bench_common import RunnerArgs


def run(task_def: dict[str, Any], caller: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    opts = _build_opts(caller)
    messages = [{"role": "user", "content": task_def["prompt"]}]

    out = caller.llm.call(messages, "openai", opts)
    if inspect.isawaitable(out):
        out = asyncio.get_event_loop().run_until_complete(out)
    answer = str(out)

    # Colmena does not surface usage from .call(); proxy span is the source of
    # truth. Report zeros — the grader treats proxy as authoritative.
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage


def _build_opts(caller: Any):
    import colmena

    opts = colmena.LlmConfigOptions()
    opts.model = caller.model_alias
    opts.api_key = caller.api_key
    opts.temperature = 0.0
    return opts
