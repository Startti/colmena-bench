"""Task 10 — Pydantic AI secrets handler (Demo #10): the NAIVE competitor arm.

Pydantic AI has no native outbound secret masking, so the idiomatic
collect-mid-conversation pattern puts the credentials straight into the LLM
transcript. This handler does the simplest idiomatic thing: run the onboarding
agent with the pasted credentials in the prompt — so the proxy's leak audit
(which scans every LLM request's messages for the secret marker) flags the leak.
It then POSTs the REAL secret values to the mock connect endpoint, and (echo
variant) makes a final call that includes the mock's echoed response, so the
echoed secret also passes through the LLM.

Contrast with Colmena (runners/colmena/runner/tasks/task10_secrets.py), whose
secure_suspend never lets the secret reach the LLM/proxy. Mirrors the LangGraph
naive arm (runners/langgraph/runner/tasks/task10_secrets.py).

Handler contract: ``run(task_def, model, args) -> (answer, usage, extras)``.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from pydantic_ai import Agent

from bench_common import RunnerArgs
from bench_common import scenario_secrets as ss

_SECRET_KEYS = ("api_key", "api_secret", "webhook_signing_secret")


def _ask_best_effort(agent: Agent, prompt: str) -> str:
    """The leak fires on the REQUEST (the proxy audits request messages); a
    transient empty/malformed completion must NOT sink the cell. Retry a few
    times, then tolerate failure by returning ''."""
    for _ in range(3):
        try:
            return str(getattr(agent.run_sync(prompt), "output", "") or "")
        except Exception:  # noqa: BLE001 — transient empty completions
            pass
    return ""


def run(
    task_def: dict[str, Any], model: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    s = ss.secrets()  # {api_key, api_secret, webhook_signing_secret} -> real fake values
    creds = (
        f"api_key={s['api_key']}, api_secret={s['api_secret']}, "
        f"webhook_signing_secret={s['webhook_signing_secret']}"
    )
    # (1) idiomatic collection: the user pastes the credentials into the chat
    #     -> they enter the LLM context -> the proxy audit flags the leak.
    onboard = Agent(model, system_prompt=ss.ONBOARDING_PROMPT,
                    model_settings={"temperature": 0.0})
    _ask_best_effort(onboard, f"Here are my credentials: {creds}")  # -> LEAK

    # (2) connect: POST the 3 REAL values to the mock.
    url = os.environ["BENCH_MOCK_URL"]
    body = json.dumps({k: s[k] for k in _SECRET_KEYS}).encode()
    resp = urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    ).read().decode()

    # (3) final call including the mock response (echo variant: response contains
    #     the secret -> it passes through the LLM here too).
    summ = Agent(model, system_prompt="Summarize the connection result in one line.",
                 model_settings={"temperature": 0.0})
    _ask_best_effort(summ, f"The connect endpoint returned: {resp}")

    return (
        "connected",
        {"input": 0, "output": 0, "cached": 0, "tool_calls": 0},
        {"arm": "naive", "received_path": os.environ.get("BENCH_MOCK_RECORD")},
    )
