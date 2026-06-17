"""Task 4 expert — Google ADK, run_sql tool over SQLite (CSV NOT in context).

The agent gets a ``run_sql(query)`` tool over an in-memory SQLite ``orders``
table and issues SQL to answer 20 analytical questions, returning a single JSON
object {Q01..Q20}.  Tokens stay small vs the naive (CSV-in-prompt) handler.

This is a SINGLE task: we register run_sql as an ADK tool (a plain Python
callable is auto-wrapped as a FunctionTool), run ONE turn with the prompt, and
drain the event stream for the final text.  ADK loops the tool internally until
the model returns its final answer.

Token accounting comes from proxy spans, so ``usage`` is all zeros by contract.
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
    RunnerArgs,
    build_questions_block,
    extract_answer_dict,
    load_orders_sqlite,
    variant_params,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

_APP = "colmena_bench"
_USER = "bench_user"


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    conn, run_sql = load_orders_sqlite(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    def run_sql_tool(query: str) -> str:
        """Run a read-only SQL SELECT against the `orders` table (all columns TEXT; CAST for math). Returns rows as text."""  # noqa: E501
        return run_sql(query)

    run_sql_tool.__name__ = "run_sql"
    run_sql_tool.__qualname__ = "run_sql"

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}"

    try:
        final_text = asyncio.run(_run_single(llm, args, run_sql_tool, prompt))
        answer = extract_answer_dict(str(final_text))
    finally:
        conn.close()

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage


async def _run_single(llm: Any, args: RunnerArgs, tool: Any, prompt: str) -> str:
    agent = Agent(
        name="data_analyst",
        model=llm,
        instruction="You are a data analyst. Use run_sql to answer the questions.",
        tools=[tool],
    )
    runner = InMemoryRunner(agent=agent, app_name=_APP)
    session_id = f"t4exp_{args.run_id}"
    session = await runner.session_service.create_session(
        app_name=_APP,
        user_id=_USER,
        session_id=session_id,
    )

    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    answer_parts: list[str] = []
    async for event in runner.run_async(
        user_id=_USER,
        session_id=session.id,
        new_message=content,
    ):
        if event.is_final_response():
            if getattr(event, "content", None) and getattr(event.content, "parts", None):
                for part in event.content.parts:
                    txt = getattr(part, "text", None)
                    if txt:
                        answer_parts.append(txt)

    return "".join(answer_parts).strip()
