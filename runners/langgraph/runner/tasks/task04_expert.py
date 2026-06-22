"""Task 4 expert — LangGraph, run_sql tool over SQLite (CSV NOT in context).

The agent gets a ``run_sql(query)`` tool over an in-memory SQLite ``orders``
table and issues SQL to answer 20 analytical questions, returning a single JSON
object {Q01..Q20}.  Tokens stay small vs the naive (CSV-in-prompt) handler.

This is a SINGLE task (no multi-turn loop), so we use ``create_react_agent`` with
NO checkpointer and invoke once with the prompt.  The agent's ToolNode executes
run_sql as many times as the model needs; we extract the last AIMessage text.

Token accounting comes from proxy spans, so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from bench_common import (
    RunnerArgs,
    build_questions_block,
    extract_answer_dict,
    load_orders_sqlite,
    variant_params,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

# Cap tool-iterations to avoid runaway (each "step" is one model + tool round).
_RECURSION_LIMIT = 50


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    conn, run_sql = load_orders_sqlite(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    @tool("run_sql")
    def run_sql_tool(query: str) -> str:
        """Run a read-only SQL SELECT against the `orders` table and return rows as text."""
        return run_sql(query)

    agent = create_react_agent(llm, [run_sql_tool])
    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}"

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": _RECURSION_LIMIT},
        )
        last_msg = result["messages"][-1]
        final_text = last_msg.content if isinstance(last_msg, AIMessage) else str(last_msg)
        answer = extract_answer_dict(str(final_text))
    finally:
        conn.close()

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
