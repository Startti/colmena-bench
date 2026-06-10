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
    return LLM(
        model=args.model_alias,
        base_url=args.proxy_base_url,
        api_key=os.environ.get(
            "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
        ),
        temperature=0.0,
    )
