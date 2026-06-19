"""Demo #7 — LangGraph many-tools handler (no lazy loading; all N tools registered).

Mirrors task04_expert's LangGraph idiom: ``create_react_agent(llm, tools)`` then a
single ``agent.invoke`` with the needle question. Tools are LangChain
``StructuredTool``s built from the toolset spec; each logs {tool, args} to
BENCH_TOOLCALL_LOG and returns its deterministic ``answer``.

Returns ({"answer": text}, zero_usage, extras).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from pydantic import create_model

from bench_common import RunnerArgs, scenario_tools

_RECURSION_LIMIT = 50
_SYSTEM = (
    "Call exactly the one tool that answers the request. Pass ONLY the argument "
    "values named in the user message, VERBATIM. Every other parameter is OPTIONAL "
    "— omit it entirely; do NOT invent or fill in values for unnamed parameters, "
    "and do NOT treat them as required. Do not validate, reformat, or reject the "
    "values. After the tool returns, report the resulting total amount number."
)


def _args_model(tool_spec: dict[str, Any]):
    fields: dict[str, Any] = {}
    for p in tool_spec["params"]:
        if p["required"]:
            fields[p["name"]] = (str, ...)
        else:
            fields[p["name"]] = (Optional[str], None)
    return create_model(f"{tool_spec['name']}_Args", **fields)


def _build_tool(tool_spec: dict[str, Any]) -> StructuredTool:
    name = tool_spec["name"]
    answer = tool_spec["answer"]

    def fn(**kwargs: Any) -> str:
        passed = {k: v for k, v in kwargs.items() if v is not None}
        scenario_tools.log_tool_call(name, passed)
        return answer

    return StructuredTool.from_function(
        func=fn,
        name=name,
        description=tool_spec["description"],
        args_schema=_args_model(tool_spec),
    )


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    try:
        tools = [_build_tool(t) for t in spec["tools"]]
        agent = create_react_agent(llm, tools)
        result = agent.invoke(
            {"messages": [SystemMessage(content=_SYSTEM), HumanMessage(content=spec["question"])]},
            config={"recursion_limit": _RECURSION_LIMIT},
        )
        last = result["messages"][-1]
        final_text = last.content if isinstance(last, AIMessage) else str(last)
        return {"answer": str(final_text)}, zero, {"n_tools": spec["n_tools"]}
    except Exception as e:  # noqa: BLE001 — record hard_error, do not crash driver
        return {"answer": ""}, zero, {"error": str(e)}
