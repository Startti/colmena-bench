"""Task 4 expert — LangChain, run_sql tool over SQLite (CSV NOT in context).

The agent gets a ``run_sql(query)`` tool over an in-memory SQLite ``orders``
table and issues SQL to answer 20 analytical questions, returning a single JSON
object {Q01..Q20}.  Tokens stay small vs the naive (CSV-in-prompt) handler.

Tool calling mirrors task05's mechanism: ``llm.bind_tools([run_sql_tool])`` then
a manual loop — invoke → if tool_calls, execute run_sql, append ToolMessage,
invoke again — until the model stops calling tools (capped) and returns the
final JSON text.

Token accounting comes from proxy spans, so ``usage`` is all zeros by contract
(the orchestrator overwrites tokens from spans).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from bench_common import (
    RunnerArgs,
    build_questions_block,
    extract_answer_dict,
    load_orders_sqlite,
    variant_params,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

_MAX_ITERS = 25


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    conn, run_sql = load_orders_sqlite(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    @tool("run_sql")
    def run_sql_tool(query: str) -> str:
        """Run a read-only SQL SELECT against the `orders` table and return rows as text."""
        return run_sql(query)

    llm_with_tools = llm.bind_tools([run_sql_tool])
    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}"
    messages: list[Any] = [HumanMessage(content=prompt)]

    final_text = ""
    try:
        for _ in range(_MAX_ITERS):
            ai_msg: AIMessage = llm_with_tools.invoke(messages)
            messages.append(ai_msg)
            tool_calls = ai_msg.tool_calls or []
            if not tool_calls:
                final_text = ai_msg.content or ""
                break
            for tc in tool_calls:
                query = tc["args"].get("query", "")
                try:
                    result = run_sql_tool.invoke(query)
                except Exception as e:  # noqa: BLE001 — surface to the agent
                    result = f"ERROR: {type(e).__name__}: {e}"
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        answer = extract_answer_dict(str(final_text))
    finally:
        conn.close()

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
