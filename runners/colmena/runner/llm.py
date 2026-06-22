"""Colmena LLM factory — drives the native module through the proxy.

Colmena's `LlmProviderFactory` reads `OPENAI_BASE_URL` **at construction
time** (when `ColmenaLlm()` builds its service containers), so we MUST set
the env var before constructing it. We drive Colmena's OpenAI adapter
(`provider="openai"`) against the proxy's OpenAI-compatible `/v1` route —
the proven path that the proxy span callback captures. The proxy maps the
`gemini-2.5-flash` alias to the real provider; Colmena only ever sees the
proxy.

NOTE: Colmena's OpenAI adapter sends only Authorization + Content-Type — it
cannot forward a custom `x-bench-run-id` header. Per-run span correlation
therefore relies on the proxy being started with the matching BENCH_RUN_ID
(see scripts/smoke_colmena.sh), not the header trick the other runners use.
"""
from __future__ import annotations

import os
from typing import Any

from bench_common import RunnerArgs


class ColmenaCaller:
    """Holds a constructed ColmenaLlm + the per-call config the handler needs."""

    def __init__(self, llm: Any, model_alias: str, api_key: str):
        self.llm = llm
        self.model_alias = model_alias
        self.api_key = api_key


def build_llm(args: RunnerArgs) -> ColmenaCaller:
    # MUST be set before constructing ColmenaLlm — the factory reads it then.
    base = args.proxy_base_url.rstrip("/")
    os.environ["OPENAI_BASE_URL"] = f"{base}/v1"

    import colmena  # imported lazily so the env var is set first

    llm = colmena.ColmenaLlm()
    api_key = os.environ.get(
        "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
    )
    return ColmenaCaller(llm=llm, model_alias=args.model_alias, api_key=api_key)
