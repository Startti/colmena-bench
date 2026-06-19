"""Demo #7 — CrewAI many-tools handler (no lazy loading; all N tools registered).

Mirrors task04_expert's CrewAI idiom (Agent + `@tool` + Crew.kickoff) but builds
N dynamically-generated tools from the toolset spec. Each tool, when called, logs
{tool, args} to BENCH_TOOLCALL_LOG and returns its deterministic `answer`.

`crewai.tools.tool(name)(fn)` introspects the wrapped function's signature to
build the tool schema, so each tool function carries an explicit per-spec
signature (built from the tool's declared params). One agent turn answers the
needle question. Returns ({"answer": text}, zero_usage, extras).
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, Task
from crewai.tools import tool

from bench_common import RunnerArgs, scenario_tools

_SYSTEM = (
    "Call exactly the one tool that answers the request. Pass ONLY the argument "
    "values named in the user message, VERBATIM. Every other parameter is OPTIONAL "
    "— omit it entirely; do NOT invent or fill in values for unnamed parameters, "
    "and do NOT treat them as required. Do not validate, reformat, or reject the "
    "values. After the tool returns, report the resulting total amount number."
)


def _build_fn(tool_spec: dict[str, Any]):
    name = tool_spec["name"]
    answer = tool_spec["answer"]

    def impl(**kwargs: Any) -> str:
        # only log args the model actually passed (drop default-None fills)
        passed = {k: v for k, v in kwargs.items() if v is not None}
        scenario_tools.log_tool_call(name, passed)
        return answer

    # Required params have no default; optional params default to None so the
    # model can call the tool with just the required args (the spec only marks
    # the first param required, and that is all the scorer checks).
    params = []
    for p in tool_spec["params"]:
        if p["required"]:
            params.append(
                inspect.Parameter(p["name"], inspect.Parameter.KEYWORD_ONLY, annotation=str)
            )
        else:
            params.append(
                inspect.Parameter(
                    p["name"], inspect.Parameter.KEYWORD_ONLY, annotation=str, default=None
                )
            )
    impl.__signature__ = inspect.Signature(params)
    impl.__name__ = name
    impl.__doc__ = tool_spec["description"]
    return impl


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    try:
        tools = [tool(t["name"])(_build_fn(t)) for t in spec["tools"]]
        agent = Agent(
            role="tool-dispatch agent",
            goal="Call the one named tool and report its result.",
            backstory=_SYSTEM,
            llm=llm,
            tools=tools,
            allow_delegation=False,
            verbose=False,
        )
        crew_task = Task(
            description=f"{_SYSTEM}\n\n{spec['question']}",
            expected_output="Just the resulting total amount number.",
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)
        result = crew.kickoff()
        return {"answer": str(result)}, zero, {"n_tools": spec["n_tools"]}
    except Exception as e:  # noqa: BLE001 — record hard_error, do not crash driver
        return {"answer": ""}, zero, {"error": str(e)}
