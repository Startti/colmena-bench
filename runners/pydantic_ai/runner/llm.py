"""Pydantic AI LLM factory — an OpenAI-compatible model pointed at the proxy.

Mirrors every other runner: we drive the framework through the LiteLLM proxy's
OpenAI-compatible `/v1` route (not a native Google client) so token usage is
captured at the proxy, and we set the `x-bench-run-id` header on every request so
the proxy routes this run's spans to `proxy/spans/run-<run_id>.jsonl`.

`build_llm` returns the pydantic_ai `OpenAIChatModel`; each task builds its own
`Agent` around it (parallel to how the LangChain runner returns a `ChatOpenAI` and
tasks bind their own tools). Temperature is applied per-agent via `model_settings`.
"""
from __future__ import annotations

import os
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

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
    return OpenAIChatModel(args.model_alias, provider=OpenAIProvider(openai_client=client))
