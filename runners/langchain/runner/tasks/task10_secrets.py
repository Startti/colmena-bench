"""Task 10 — LangChain secrets handler (Demo #10): the NAIVE arm.

The idiomatic way to collect a secret mid-conversation in plain LangChain is to
just ask the user and let them paste it into the chat — which puts the secret
value straight into the LLM transcript. This handler does exactly that, so the
proxy's leak audit (which scans every LLM request's messages for the secret
marker) flags the leak. Then it POSTs the REAL secret values to the mock connect
endpoint, and makes a final LLM call that includes the mock's response (so in the
echo variant the echoed secret also passes through the LLM).

Contrast with Colmena (runners/colmena/runner/tasks/task10_secrets.py), whose
secure_suspend never lets the secret reach the LLM/proxy.

LLM wiring mirrors task06_refund.py: a proxy-wired ``llm`` invoked via
``llm.invoke([...])`` whose return carries ``.content``. We pass chat tuples
``(role, content)`` (LangChain accepts role/content 2-tuples directly).

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from bench_common import RunnerArgs
from bench_common import scenario_secrets as ss


def _ask(llm: Any, msgs: list[tuple[str, str]]) -> str:
    """One LLM call over role/content tuples (LangChain idiom from task06_refund:
    ``llm.invoke([...])`` -> ``.content``). The secret values live in ``msgs`` so
    the proxy audit sees them."""
    return str(llm.invoke(msgs).content)


def _ask_best_effort(llm: Any, msgs: list[tuple[str, str]]) -> str:
    """The leak fires on the REQUEST (proxy audits request messages); a transient
    empty/malformed completion must NOT sink the cell. Retry a few times, then
    tolerate failure by returning ''."""
    last = None
    for _ in range(3):
        try:
            return _ask(llm, msgs)
        except Exception as e:  # noqa: BLE001 — transient empty completions
            last = e
    return ""


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    s = ss.secrets()  # {api_key, api_secret, webhook_signing_secret} -> real fake values
    creds = (
        f"api_key={s['api_key']}, api_secret={s['api_secret']}, "
        f"webhook_signing_secret={s['webhook_signing_secret']}"
    )
    # (1) idiomatic collection: the user pastes the credentials into the chat
    #     -> they enter the LLM context -> the proxy audit flags the leak.
    msgs = [
        ("system", ss.ONBOARDING_PROMPT),
        ("assistant", "Please paste your API key, API secret, and webhook signing secret."),
        ("user", f"Here are my credentials: {creds}"),
    ]
    _ = _ask_best_effort(llm, msgs)  # the secrets are now in the prompt -> LEAK

    # (2) connect: POST the 3 REAL values to the mock.
    url = os.environ["BENCH_MOCK_URL"]
    body = json.dumps(
        {k: s[k] for k in ("api_key", "api_secret", "webhook_signing_secret")}
    ).encode()
    resp = urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    ).read().decode()

    # (3) final call including the mock response (echo variant: response contains
    #     the secret -> it passes through the LLM here too).
    _ = _ask_best_effort(
        llm,
        [
            ("system", "Summarize the connection result in one line."),
            ("user", f"The connect endpoint returned: {resp}"),
        ],
    )

    return (
        "connected",
        {"input": 0, "output": 0, "cached": 0, "tool_calls": 0},
        {"arm": "naive", "received_path": os.environ.get("BENCH_MOCK_RECORD")},
    )
