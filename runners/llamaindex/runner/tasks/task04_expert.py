"""Task 4 expert — LlamaIndex, run_sql tool over SQLite (CSV NOT in context).

The agent gets a ``run_sql(query)`` tool over an in-memory SQLite ``orders``
table and issues SQL to answer 20 analytical questions, returning a single JSON
object {Q01..Q20}.  Tokens stay small vs the naive (CSV-in-prompt) handler.

This is a SINGLE task: we build a ``FunctionAgent`` (v0.14+ AgentWorkflow API)
with a ``FunctionTool`` wrapping run_sql, then ``.run(prompt)`` once and extract
the final text.  The LLM factory already sets ``is_function_calling_model=True``.

Token accounting comes from proxy spans, so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import FunctionTool

from bench_common import (
    RunnerArgs,
    build_questions_block,
    extract_answer_dict,
    load_orders_sqlite,
    variant_params,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    conn, run_sql = load_orders_sqlite(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    def run_sql_fn(query: str) -> str:
        """Run a read-only SQL SELECT against the `orders` table and return rows as text."""
        return run_sql(query)

    sql_tool = FunctionTool.from_defaults(
        fn=run_sql_fn,
        name="run_sql",
        description=(
            "Run a read-only SQL SELECT against the `orders` table "
            "(all columns TEXT; CAST for math). Returns rows as text."
        ),
    )

    agent = FunctionAgent(
        tools=[sql_tool],
        llm=llm,
        system_prompt="You are a data analyst. Use run_sql to answer the questions.",
        verbose=False,
        timeout=None,  # disable the 45s default — many SQL round-trips can take longer
    )

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}"

    async def _run() -> str:
        # agent.run() returns a WorkflowHandler that must be created AND awaited
        # inside a running event loop.  max_iterations is bumped well above the
        # default 20 — answering 20 questions needs many SQL round-trips plus
        # reasoning steps, which would otherwise trip the iteration cap.
        result = await agent.run(user_msg=prompt, max_iterations=60)
        if hasattr(result, "response"):
            return result.response.content or ""
        return str(result)

    try:
        final_text = asyncio.run(_run())
        answer = extract_answer_dict(str(final_text))
    finally:
        conn.close()

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
