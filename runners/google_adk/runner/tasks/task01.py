"""Task 1 — hello world, on Google ADK.

Builds a minimal single-agent app and runs one turn through ADK's Runner +
in-memory session, so the measured overhead reflects ADK's agent machinery.
ADK is async; we drive it from a fresh event loop.
"""
from __future__ import annotations

import asyncio
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from bench_common import RunnerArgs

_APP = "colmena_bench"
_USER = "bench_user"


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    agent = Agent(
        name="responder",
        model=llm,
        instruction="Respond exactly as the user asks.",
    )
    runner = InMemoryRunner(agent=agent, app_name=_APP)

    answer, usage = asyncio.run(_run_once(runner, task_def["prompt"]))
    return answer, usage


async def _run_once(runner: Any, prompt: str) -> tuple[str, dict[str, int]]:
    session = await runner.session_service.create_session(app_name=_APP, user_id=_USER)
    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    answer_parts: list[str] = []
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}

    async for event in runner.run_async(
        user_id=_USER, session_id=session.id, new_message=content
    ):
        # Accumulate any final text the agent produces.
        if getattr(event, "content", None) and getattr(event.content, "parts", None):
            for part in event.content.parts:
                if getattr(part, "text", None):
                    answer_parts.append(part.text)
        # Token usage rides on the model-response events when available.
        meta = getattr(event, "usage_metadata", None)
        if meta is not None:
            usage["input"] = int(getattr(meta, "prompt_token_count", 0) or 0)
            usage["output"] = int(getattr(meta, "candidates_token_count", 0) or 0)
            usage["cached"] = int(getattr(meta, "cached_content_token_count", 0) or 0)

    return "".join(answer_parts).strip(), usage
