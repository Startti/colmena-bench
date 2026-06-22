"""LangGraph LLM factory — ChatOpenAI pointed at the proxy.

LangGraph orchestrates LangChain model objects, so the LLM wiring is
identical to the LangChain runner: ChatOpenAI against the proxy /v1 route,
with `x-bench-run-id` for span correlation.
"""
from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI

from bench_common import RunnerArgs


def build_llm(args: RunnerArgs) -> Any:
    base = args.proxy_base_url.rstrip("/")
    return ChatOpenAI(
        model=args.model_alias,
        base_url=f"{base}/v1",
        api_key=os.environ.get(
            "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
        ),
        temperature=0.0,
        default_headers={"x-bench-run-id": args.run_id},
    )
