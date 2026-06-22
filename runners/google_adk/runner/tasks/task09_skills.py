"""Demo #9 — Google ADK handler: naive (prompt-stuff) arm of the Skills demo.

Stuffs the entire knowledge corpus into the system prompt (the naive strategy
Colmena's load_skill is designed to beat) and asks one question. Tokens are
measured by the driver from proxy spans; usage is returned as zeros.

ADK requires an Agent + Runner to make a call, so we mirror the minimal
single-turn form from task01/task08 with NO tools: the corpus is the agent's
`instruction` (the system slot) and the question is the user content. Only the
`naive` arm is implemented here; non-naive arms raise ValueError for now.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from bench_common import RunnerArgs
from bench_common import scenario_skills as sk

_APP = "colmena_bench"
_USER = "bench_user"


async def _run_once(runner: Any, prompt: str) -> str:
    session = await runner.session_service.create_session(app_name=_APP, user_id=_USER)
    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    answer_parts: list[str] = []
    async for event in runner.run_async(
        user_id=_USER, session_id=session.id, new_message=content
    ):
        if getattr(event, "content", None) and getattr(event.content, "parts", None):
            for part in event.content.parts:
                if getattr(part, "text", None):
                    answer_parts.append(part.text)
    return "".join(answer_parts).strip()


def _ask_llm(llm: Any, system: str, user: str) -> str:
    # Minimal single-turn ADK agent, NO tools (mirror task01/task08). The
    # corpus is the agent instruction (system slot); the question is the user
    # content. `llm` is the proxy-wired LiteLlm passed in by the driver.
    agent = Agent(
        name="finance_analyst",
        model=llm,
        instruction=system,
    )
    runner = InMemoryRunner(agent=agent, app_name=_APP)
    return asyncio.run(_run_once(runner, user))


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    arm = os.environ.get("BENCH_SKILLS_ARM", "naive")
    skills_dir = os.environ["BENCH_SKILLS_DIR"]
    qid = os.environ["BENCH_QUESTION_ID"]
    question = next(q for q in sk.QUESTION_BANK if q.id == qid)

    if arm != "naive":
        raise ValueError(f"arm {arm!r} not supported")

    system = sk.build_naive_system_prompt(skills_dir)
    answer = _ask_llm(llm, system, question.text)

    usage = {"input": 0, "output": 0, "cached": 0}
    extras = {"arm": arm, "question_id": qid}
    return str(answer), usage, extras
