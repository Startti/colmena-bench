"""Google ADK LLM factory — LiteLlm pointed at the proxy.

ADK reaches non-Gemini-native models through its `LiteLlm` wrapper. We use
the `openai/<alias>` form against the proxy /v1 route (the ADK-native Gemini
path would bypass the proxy). `extra_headers` carries `x-bench-run-id`; if
ADK/LiteLLM doesn't propagate it, correlation falls back to the proxy
session id.
"""
from __future__ import annotations

import os
from typing import Any

from google.adk.models.lite_llm import LiteLlm

from bench_common import RunnerArgs


def build_llm(args: RunnerArgs) -> Any:
    base = args.proxy_base_url.rstrip("/")
    return LiteLlm(
        model=f"openai/{args.model_alias}",
        api_base=f"{base}/v1",
        api_key=os.environ.get(
            "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
        ),
        temperature=0.0,
        extra_headers={"x-bench-run-id": args.run_id},
    )
