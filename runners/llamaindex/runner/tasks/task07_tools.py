"""Demo #7 — LlamaIndex many-tools handler (no lazy loading; all N tools registered).

Mirrors task04_expert's LlamaIndex idiom: build ``FunctionTool``s, register them on
a ``FunctionAgent`` (AgentWorkflow API), then ``asyncio.run(agent.run(...))`` once
on the needle question. The N tools come from the toolset spec; each logs
{tool, args} to BENCH_TOOLCALL_LOG and returns its deterministic ``answer``.

Each tool's parameter schema is built from the spec via a pydantic ``fn_schema``
(required param required; the rest optional). Returns
({"answer": text}, zero_usage, extras).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import FunctionTool
from pydantic import create_model

from bench_common import RunnerArgs, scenario_tools

_SYSTEM = (
    "Call exactly the one tool that answers the request. Pass ONLY the argument "
    "values named in the user message, VERBATIM. Every other parameter is OPTIONAL "
    "— omit it entirely; do NOT invent or fill in values for unnamed parameters, "
    "and do NOT treat them as required. Do not validate, reformat, or reject the "
    "values. After the tool returns, report the resulting total amount number."
)


def _fn_schema(tool_spec: dict[str, Any]):
    fields: dict[str, Any] = {}
    for p in tool_spec["params"]:
        if p["required"]:
            fields[p["name"]] = (str, ...)
        else:
            fields[p["name"]] = (Optional[str], None)
    return create_model(f"{tool_spec['name']}_Args", **fields)


def _build_tool(tool_spec: dict[str, Any]) -> FunctionTool:
    name = tool_spec["name"]
    answer = tool_spec["answer"]

    def fn(**kwargs: Any) -> str:
        passed = {k: v for k, v in kwargs.items() if v is not None}
        scenario_tools.log_tool_call(name, passed)
        return answer

    return FunctionTool.from_defaults(
        fn=fn,
        name=name,
        description=tool_spec["description"],
        fn_schema=_fn_schema(tool_spec),
    )


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    try:
        tools = [_build_tool(t) for t in spec["tools"]]
        agent = FunctionAgent(
            tools=tools,
            llm=llm,
            system_prompt=_SYSTEM,
            verbose=False,
            timeout=None,
        )

        async def _run() -> str:
            result = await agent.run(user_msg=spec["question"], max_iterations=12)
            if hasattr(result, "response"):
                return result.response.content or ""
            return str(result)

        final_text = asyncio.run(_run())
        return {"answer": str(final_text)}, zero, {"n_tools": spec["n_tools"]}
    except Exception as e:  # noqa: BLE001 — record hard_error, do not crash driver
        return {"answer": ""}, zero, {"error": str(e)}
