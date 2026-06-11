"""LlamaIndex LLM factory — OpenAILike pointed at the proxy.

`OpenAILike` speaks the OpenAI dialect to an arbitrary `api_base`, so it
routes through the proxy /v1 route (the LlamaIndex-native OpenAI/Gemini
wrappers would bypass it). `default_headers` carries `x-bench-run-id` for
span correlation.
"""
from __future__ import annotations

import os
from typing import Any

from llama_index.llms.openai_like import OpenAILike

from bench_common import RunnerArgs


def build_llm(args: RunnerArgs) -> Any:
    base = args.proxy_base_url.rstrip("/")
    return OpenAILike(
        model=args.model_alias,
        api_base=f"{base}/v1",
        api_key=os.environ.get(
            "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
        ),
        is_chat_model=True,
        temperature=0.0,
        default_headers={"x-bench-run-id": args.run_id},
    )
