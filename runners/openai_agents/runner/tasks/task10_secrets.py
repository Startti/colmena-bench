"""Task 10 — OpenAI Agents SDK secrets handler (Demo #10): the NAIVE competitor arm.

No native outbound masking, so the idiomatic collect-mid-conversation pattern puts
the credentials into the LLM transcript. Run the onboarding agent with the pasted
credentials in the prompt (the proxy leak audit flags them), POST the real values to
the mock connect endpoint, then (echo variant) make a final call over the echoed
response. Mirrors the LangGraph/Pydantic-AI naive arms.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from agents import Agent, ModelSettings, Runner

from bench_common import RunnerArgs
from bench_common import scenario_secrets as ss

_SECRET_KEYS = ("api_key", "api_secret", "webhook_signing_secret")


def _ask_best_effort(agent: Agent, prompt: str) -> str:
    """The leak fires on the REQUEST; a transient empty completion must not sink
    the cell. Retry a few times, then tolerate failure."""
    for _ in range(3):
        try:
            return str(Runner.run_sync(agent, prompt).final_output or "")
        except Exception:  # noqa: BLE001 — transient empty completions
            pass
    return ""


def run(
    task_def: dict[str, Any], model: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    s = ss.secrets()
    creds = (
        f"api_key={s['api_key']}, api_secret={s['api_secret']}, "
        f"webhook_signing_secret={s['webhook_signing_secret']}"
    )
    # (1) idiomatic collection: the pasted credentials enter the LLM context -> LEAK.
    onboard = Agent(name="Onboarding", instructions=ss.ONBOARDING_PROMPT, model=model,
                    model_settings=ModelSettings(temperature=0.0))
    _ask_best_effort(onboard, f"Here are my credentials: {creds}")

    # (2) connect: POST the 3 REAL values to the mock.
    url = os.environ["BENCH_MOCK_URL"]
    body = json.dumps({k: s[k] for k in _SECRET_KEYS}).encode()
    resp = urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    ).read().decode()

    # (3) final call including the mock response (echo variant re-leaks the secret).
    summ = Agent(name="Summarizer", instructions="Summarize the connection result in one line.",
                 model=model, model_settings=ModelSettings(temperature=0.0))
    _ask_best_effort(summ, f"The connect endpoint returned: {resp}")

    return (
        "connected",
        {"input": 0, "output": 0, "cached": 0, "tool_calls": 0},
        {"arm": "naive", "received_path": os.environ.get("BENCH_MOCK_RECORD")},
    )
