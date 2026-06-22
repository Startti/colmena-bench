"""Task 4 naive — Google ADK, CSV injected into the prompt.

Single-agent app, one turn through ADK's Runner + in-memory session.
ADK is async; we drive it from a fresh event loop.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from bench_common import (
    RunnerArgs, variant_params, read_csv_text, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

_APP = "colmena_bench"
_USER = "bench_user"


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    csv_text = read_csv_text(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}\n\nCSV DATA:\n{csv_text}"

    agent = Agent(
        name="responder",
        model=llm,
        instruction="You are a data analyst. Answer the user's questions from the CSV.",
    )
    runner = InMemoryRunner(agent=agent, app_name=_APP)

    text, usage = asyncio.run(_run_once(runner, prompt))
    answer = extract_answer_dict(str(text))
    return answer, usage


async def _run_once(runner: Any, prompt: str) -> tuple[str, dict[str, int]]:
    session = await runner.session_service.create_session(app_name=_APP, user_id=_USER)
    content = types.Content(role="user", parts=[types.Part(text=prompt)])

    answer_parts: list[str] = []
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}

    async for event in runner.run_async(
        user_id=_USER, session_id=session.id, new_message=content
    ):
        if getattr(event, "content", None) and getattr(event.content, "parts", None):
            for part in event.content.parts:
                if getattr(part, "text", None):
                    answer_parts.append(part.text)
        meta = getattr(event, "usage_metadata", None)
        if meta is not None:
            usage["input"] = int(getattr(meta, "prompt_token_count", 0) or 0)
            usage["output"] = int(getattr(meta, "candidates_token_count", 0) or 0)
            usage["cached"] = int(getattr(meta, "cached_content_token_count", 0) or 0)

    return "".join(answer_parts).strip(), usage
