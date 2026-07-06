"""Demo #7 — OpenAI Agents SDK many-tools handler (single-turn probe; no lazy loading).

Builds N dynamic tools from the toolset spec (``FunctionTool`` with an explicit
JSON schema + an async ``on_invoke_tool`` callback) and binds them ALL to the agent
— the Agents SDK sends every tool schema each turn (the competitor baseline). One
run answers the needle question; each tool logs {tool, args} to BENCH_TOOLCALL_LOG
and returns its deterministic answer.

Returns ({"answer": text}, zero_usage, {"n_tools": N}).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agents import Agent, FunctionTool, ModelSettings, Runner

from bench_common import RunnerArgs, scenario_tools

_SYSTEM = (
    "Call exactly the one tool that answers the request. Pass ONLY the argument "
    "values named in the user message, VERBATIM. Every other parameter is OPTIONAL "
    "— omit it entirely; do NOT invent or fill in values for unnamed parameters, "
    "and do NOT treat them as required. Do not validate, reformat, or reject the "
    "values. After the tool returns, report the resulting total amount number."
)


def _json_schema(tool_spec: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in tool_spec["params"]:
        props[p["name"]] = {"type": "string"}
        if p["required"]:
            required.append(p["name"])
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def _make_tool(tool_spec: dict[str, Any]) -> FunctionTool:
    name = tool_spec["name"]
    answer = tool_spec["answer"]

    async def on_invoke(_ctx: Any, args_json: str) -> str:
        try:
            passed = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            passed = {}
        passed = {k: v for k, v in passed.items() if v is not None}
        scenario_tools.log_tool_call(name, passed)
        return answer

    return FunctionTool(
        name=name,
        description=tool_spec["description"],
        params_json_schema=_json_schema(tool_spec),
        on_invoke_tool=on_invoke,
        strict_json_schema=False,
    )


def run(
    task_def: dict[str, Any], model: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    try:
        tools = [_make_tool(t) for t in spec["tools"]]
        agent = Agent(name="ToolDispatch", instructions=_SYSTEM, tools=tools, model=model,
                      model_settings=ModelSettings(temperature=0.0))
        result = Runner.run_sync(agent, spec["question"])
        return {"answer": str(result.final_output or "")}, zero, {"n_tools": spec["n_tools"]}
    except Exception as e:  # noqa: BLE001 — record hard_error, do not crash the driver
        return {"answer": ""}, zero, {"error": str(e)}
