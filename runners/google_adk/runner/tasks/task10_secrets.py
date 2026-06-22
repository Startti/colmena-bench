"""Task 10 — Google ADK secrets handler (Demo #10): the NAIVE arm.

ADK has no native OUTBOUND secret masking: a user message flows straight into the
LLM via the Runner event loop. The idiomatic collect-mid-conversation pattern
therefore puts the secret into the LLM transcript. This handler runs the
onboarding turn through a one-shot ``Agent`` + ``InMemoryRunner`` (the same
``_run_agent_turn`` shape as task06_refund.py / task01) with the pasted
credentials in the user message, so the secret values land in the LLM messages and
the proxy's leak audit flags the leak. Then it POSTs the REAL secret values to the
mock connect endpoint, and runs a final turn including the mock's response (echo
variant -> the echoed secret also passes through the LLM).

Contrast with Colmena (runners/colmena/runner/tasks/task10_secrets.py), whose
secure_suspend never lets the secret reach the LLM/proxy.

ADK's one-shot ``Agent`` takes a single ``instruction`` (system) plus one user
message; it has no explicit assistant turn, so the assistant line is folded into
the user prompt text. The KEY requirement — the 3 secret values appear in the LLM
message content — holds. LLM wiring mirrors task06_refund's
``_run_agent_turn(agent, suffix, run_id, prompt)`` over ``InMemoryRunner``.

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from bench_common import RunnerArgs
from bench_common import scenario_secrets as ss

_APP = "colmena_bench"
_USER = "bench_user"


async def _run_agent_turn(agent: Agent, session_suffix: str, run_id: str, prompt: str) -> str:
    """Run ONE prompt through an Agent and drain the event stream for final text
    (copied from task06_refund._run_agent_turn). A fresh InMemoryRunner + session
    per call keeps turns isolated."""
    runner = InMemoryRunner(agent=agent, app_name=_APP)
    session_id = f"{session_suffix}_{run_id}"
    session = await runner.session_service.create_session(
        app_name=_APP, user_id=_USER, session_id=session_id
    )
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    answer_parts: list[str] = []
    async for event in runner.run_async(
        user_id=_USER, session_id=session.id, new_message=content
    ):
        if event.is_final_response():
            if getattr(event, "content", None) and getattr(event.content, "parts", None):
                for part in event.content.parts:
                    txt = getattr(part, "text", None)
                    if txt:
                        answer_parts.append(txt)
    return "".join(answer_parts).strip()


def _ask(llm: Any, msgs: list[tuple[str, str]], suffix: str, run_id: str) -> str:
    """One LLM call through an ADK Agent + InMemoryRunner (task06_refund idiom).
    The system line becomes the Agent ``instruction``; assistant/user lines fold
    into the user prompt (ADK has no explicit assistant turn). The secret values
    live in the prompt so the proxy audit sees them."""
    system = "\n".join(c for r, c in msgs if r == "system")
    prompt = "\n".join(
        f"{'Assistant' if r == 'assistant' else 'User'}: {c}"
        for r, c in msgs
        if r in ("assistant", "user")
    )
    agent = Agent(
        name=f"secrets_{suffix}",
        model=llm,
        instruction=system or "You help users connect their account to the payments provider.",
    )
    return asyncio.run(_run_agent_turn(agent, suffix, run_id, prompt))


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
    _ = _ask(llm, msgs, "t10collect", args.run_id)  # secrets in the prompt -> LEAK

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
        "t10final",
        args.run_id,
    )

    return (
        "connected",
        {"input": 0, "output": 0, "cached": 0, "tool_calls": 0},
        {"arm": "naive", "received_path": os.environ.get("BENCH_MOCK_RECORD")},
    )
