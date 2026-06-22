"""Demo #7 — LangChain many-tools handler (no lazy loading; all N tools bound).

Mirrors task04_expert's LangChain idiom: build tools, ``llm.bind_tools(tools)``,
then a manual invoke -> ToolMessage -> invoke loop, dispatching by tool name. The
N tools come from the toolset spec; each logs {tool, args} to BENCH_TOOLCALL_LOG
and returns its deterministic ``answer``.

Each tool is a ``StructuredTool`` whose args_schema is a pydantic model built from
the tool's declared params (required param required; the rest optional). One agent
turn answers the needle question. Returns ({"answer": text}, zero_usage, extras).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import create_model

from bench_common import RunnerArgs, scenario_tools

_MAX_ITERS = 8
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
        by_name = {t.name: t for t in tools}
        llm_with_tools = llm.bind_tools(tools)
        messages: list[Any] = [
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=spec["question"]),
        ]
        final_text = ""
        for _ in range(_MAX_ITERS):
            ai_msg: AIMessage = llm_with_tools.invoke(messages)
            messages.append(ai_msg)
            tool_calls = ai_msg.tool_calls or []
            if not tool_calls:
                final_text = ai_msg.content or ""
                break
            for tc in tool_calls:
                tool = by_name.get(tc["name"])
                try:
                    result = tool.invoke(tc["args"]) if tool else f"unknown tool {tc['name']}"
                except Exception as e:  # noqa: BLE001 — surface to the agent
                    result = f"ERROR: {type(e).__name__}: {e}"
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        return {"answer": str(final_text)}, zero, {"n_tools": spec["n_tools"]}
    except Exception as e:  # noqa: BLE001 — record hard_error, do not crash driver
        return {"answer": ""}, zero, {"error": str(e)}
