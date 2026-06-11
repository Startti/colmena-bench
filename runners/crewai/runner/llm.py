"""CrewAI LLM factory — points at the LiteLLM proxy.

See `docs/base_url_compatibility.md` for why we override `base_url` instead of
using a provider-specific wrapper. The proxy is the source of truth for
token counts (METHODOLOGY §4).
"""
from __future__ import annotations

import os
from typing import Any

from crewai import LLM

from .common import RunnerArgs


def build_llm(args: RunnerArgs) -> Any:
    # The `openai/` prefix forces CrewAI/LiteLLM down the OpenAI-compatible
    # HTTP path that honours `base_url`, routing every call through our proxy.
    # Without it, CrewAI 1.x picks a "native provider" (e.g. GeminiCompletion)
    # that talks straight to Google and bypasses the proxy — see
    # docs/base_url_compatibility.md. The proxy speaks OpenAI dialect for all
    # aliases, so it resolves `gemini-2.5-flash` correctly.
    #
    # `x-bench-run-id` lets the proxy route this run's spans to
    # proxy/spans/run-<run_id>.jsonl (see proxy/spans_callback.py). Without it
    # the grader can't correlate proxy tokens to this run.
    return LLM(
        model=f"openai/{args.model_alias}",
        base_url=args.proxy_base_url,
        api_key=os.environ.get(
            "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
        ),
        temperature=0.0,
        extra_headers={"x-bench-run-id": args.run_id},
    )
