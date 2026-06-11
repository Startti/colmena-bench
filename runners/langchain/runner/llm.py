"""LangChain LLM factory — ChatOpenAI pointed at the proxy.

We use `ChatOpenAI` (the OpenAI-compatible client) against the proxy's `/v1`
route rather than `langchain_google_genai`, which would talk straight to
Google and bypass token capture (see docs/base_url_compatibility.md). The
proxy resolves the alias to the real provider.

`default_headers` carries `x-bench-run-id` so the proxy routes this run's
spans to proxy/spans/run-<run_id>.jsonl for correlation.
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
