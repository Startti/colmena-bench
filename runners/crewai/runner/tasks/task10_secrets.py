"""Task 10 — CrewAI secrets handler (Demo #10): the NAIVE arm.

CrewAI has no native OUTBOUND secret masking: anything the user provides flows
into the task description / agent context and straight into the LLM call. The
idiomatic collect-mid-conversation pattern therefore puts the secret into the LLM
transcript. This handler folds the onboarding conversation (assistant asks, user
pastes credentials) into a one-shot Agent + Task + ``Crew(...).kickoff()`` — the
same one-shot Agent/Task/Crew shape used in task06_refund.py's
``_confirm_with_masked_tool`` — so the secret values land in the LLM messages and
the proxy's leak audit flags the leak. Then it POSTs the REAL secret values to the
mock connect endpoint, and runs a final Crew including the mock's response (echo
variant -> the echoed secret also passes through the LLM).

Contrast with Colmena (runners/colmena/runner/tasks/task10_secrets.py), whose
secure_suspend never lets the secret reach the LLM/proxy.

CrewAI cannot take an explicit "assistant" turn in a one-shot Task, so the
assistant line is folded into the task description text alongside the user paste —
the KEY requirement is that the 3 secret values appear in the content sent to the
LLM, which they do (task06_refund builds the Task ``description`` the same way and
runs it via ``Crew(agents=[agent], tasks=[crew_task]).kickoff()``).

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from crewai import Agent, Crew, Task

from bench_common import RunnerArgs
from bench_common import scenario_secrets as ss


def _ask(llm: Any, msgs: list[tuple[str, str]]) -> str:
    """One LLM call via a one-shot Agent + Task + ``Crew(...).kickoff()`` (mirrors
    task06_refund's confirm: build a Task ``description`` and run
    ``Crew(agents=[agent], tasks=[crew_task]).kickoff()``). CrewAI has no explicit
    assistant turn in a one-shot Task, so system/assistant/user lines are folded
    into the task description; the secret values appear there so the proxy audit
    sees them."""
    system = "\n".join(c for r, c in msgs if r == "system")
    convo = "\n".join(
        f"{'Assistant' if r == 'assistant' else 'User'}: {c}"
        for r, c in msgs
        if r in ("assistant", "user")
    )
    agent = Agent(
        role="onboarding assistant",
        goal="Help the user connect their account.",
        backstory=system or "You help users connect their account to the payments provider.",
        llm=llm, allow_delegation=False, verbose=False,
    )
    crew_task = Task(
        description=convo,
        expected_output="A short reply continuing the conversation.",
        agent=agent,
    )
    return str(Crew(agents=[agent], tasks=[crew_task], verbose=False).kickoff())


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
    _ = _ask(llm, msgs)  # the secrets are now in the prompt -> LEAK

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
    _ = _ask(
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
