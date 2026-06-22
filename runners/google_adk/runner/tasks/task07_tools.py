"""Demo #7 — Google ADK many-tools handler (no lazy loading; all N tools registered).

Mirrors task04_expert's ADK idiom: register plain Python callables as tools on an
``Agent`` (auto-wrapped as FunctionTools), run ONE turn with ``InMemoryRunner``,
and drain the event stream for the final text. The N tools come from the toolset
spec; each logs {tool, args} to BENCH_TOOLCALL_LOG and returns its deterministic
``answer``.

ADK builds each tool's schema by introspecting the callable's signature, so every
tool function carries an explicit per-spec signature: the required param has no
default; optional params default to None (and are dropped from the call log).
Returns ({"answer": text}, zero_usage, extras).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from bench_common import RunnerArgs, scenario_tools

_APP = "colmena_bench"
_USER = "bench_user"
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
        passed = {k: v for k, v in kwargs.items() if v is not None}
        scenario_tools.log_tool_call(name, passed)
        return answer

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
    impl.__qualname__ = name
    impl.__doc__ = tool_spec["description"]
    return impl


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    try:
        tools = [_build_fn(t) for t in spec["tools"]]
        final_text = asyncio.run(_run_single(llm, args, tools, spec["question"]))
        return {"answer": str(final_text)}, zero, {"n_tools": spec["n_tools"]}
    except Exception as e:  # noqa: BLE001 — record hard_error, do not crash driver
        return {"answer": ""}, zero, {"error": str(e)}


async def _run_single(llm: Any, args: RunnerArgs, tools: list, question: str) -> str:
    agent = Agent(
        name="tool_dispatch_agent",
        model=llm,
        instruction=_SYSTEM,
        tools=tools,
    )
    runner = InMemoryRunner(agent=agent, app_name=_APP)
    session = await runner.session_service.create_session(
        app_name=_APP, user_id=_USER, session_id=f"t7tools_{args.run_id}"
    )
    content = types.Content(role="user", parts=[types.Part(text=question)])
    answer_parts: list[str] = []
    async for event in runner.run_async(
        user_id=_USER, session_id=session.id, new_message=content
    ):
        if event.is_final_response():
            if getattr(event, "content", None) and getattr(event.content, "parts", None):
                for part in event.content.parts:
                    txt = getattr(part, "text", None)
                    if txt:
                        answer_parts.append(txt)
    return "".join(answer_parts).strip()
