"""OpenAI Agents SDK LLM factory — global client pointed at the proxy.

The Agents SDK uses PROCESS-GLOBAL client/config rather than a per-agent client, so
``build_llm`` wires the globals and returns the model string that each task passes
to ``Agent(model=...)``. Each runner subprocess is one benchmark run, so the single
global client (carrying this run's ``x-bench-run-id`` header) is correct.

Three make-or-break settings (per the connectivity spike):
  * ``set_default_openai_client`` — an ``AsyncOpenAI`` at the proxy's ``/v1`` route
    with the master key and the ``x-bench-run-id`` header (so the proxy buckets
    spans to ``proxy/spans/run-<run_id>.jsonl``).
  * ``set_default_openai_api("chat_completions")`` — third-party (non-OpenAI)
    endpoints need Chat Completions, not the Responses API.
  * ``set_tracing_disabled(True)`` — the tracing exporter would try to reach OpenAI
    directly and hang/err.
"""
from __future__ import annotations

import os
from typing import Any

from agents import (
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from bench_common import RunnerArgs


def build_llm(args: RunnerArgs) -> Any:
    base = args.proxy_base_url.rstrip("/")
    client = AsyncOpenAI(
        base_url=f"{base}/v1",
        api_key=os.environ.get(
            "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
        ),
        default_headers={"x-bench-run-id": args.run_id},
    )
    set_default_openai_client(client)
    set_default_openai_api("chat_completions")
    set_tracing_disabled(True)
    return args.model_alias  # tasks use this as Agent(model=...)
