"""Demo #7 — Pydantic AI many-tools handler (single-turn probe; no lazy loading).

Mirrors the LangChain task07 idiom: build N tools from the toolset spec and bind
them ALL to the agent (Pydantic AI has no lazy tool loading, so every schema is
sent — the competitor baseline). One agent turn answers the needle question; each
tool logs {tool, args} to BENCH_TOOLCALL_LOG and returns its deterministic answer.

Dynamic tools are built with ``Tool.from_schema`` (explicit JSON schema per the
spec's declared params: required params required, the rest optional strings).

Returns ({"answer": text}, zero_usage, {"n_tools": N}). Token accounting is via
proxy spans (the driver measures colmena by delta and competitors by run-id file).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, Tool

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


def _make_tool(tool_spec: dict[str, Any]) -> Tool:
    name = tool_spec["name"]
    answer = tool_spec["answer"]

    def fn(**kwargs: Any) -> str:
        passed = {k: v for k, v in kwargs.items() if v is not None}
        scenario_tools.log_tool_call(name, passed)
        return answer

    return Tool.from_schema(
        fn, name=name, description=tool_spec["description"],
        json_schema=_json_schema(tool_spec),
    )


def run(
    task_def: dict[str, Any], model: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    try:
        tools = [_make_tool(t) for t in spec["tools"]]
        agent = Agent(model, system_prompt=_SYSTEM, tools=tools,
                      model_settings={"temperature": 0.0})
        result = agent.run_sync(spec["question"])
        return {"answer": str(getattr(result, "output", "") or "")}, zero, {"n_tools": spec["n_tools"]}
    except Exception as e:  # noqa: BLE001 — record hard_error, do not crash the driver
        return {"answer": ""}, zero, {"error": str(e)}
