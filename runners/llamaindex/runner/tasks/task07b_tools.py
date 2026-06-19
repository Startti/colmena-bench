"""Demo #7 v2 — LlamaIndex MULTI-TURN many-tools handler.

Mirrors ``task07_tools`` (N ``FunctionTool``s built from a spec, each logging its
call and returning a deterministic answer, registered on a ``FunctionAgent``) but
replays a fixed multi-turn conversation like ``task05``: a single reused
``Context`` whose ``ChatMemoryBuffer`` persists across all turns — LlamaIndex's
native multi-turn memory — so all ~30 tool schemas are re-sent every turn (the
whole point — competitors pay the full schema tax).

The needle varies per turn, so we precompute a name->answer map: a tool that is
some turn's needle returns that turn's ``expected_answer``; every other tool
returns ``CALLED:<name>``. Token accounting is via proxy spans bucketed by
``extras.turn_boundaries`` (one before turn 0 + one after each turn).
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import Context
from pydantic import create_model

from bench_common import RunnerArgs, scenario_tools

_SYSTEM = (
    "You are a tool-dispatch agent. Each turn the user makes one request naming "
    "the exact argument values to pass. Choose the single tool that fulfills the "
    "request and call it with those literal argument values verbatim. Pass ONLY "
    "the argument values named in the request; every other parameter is OPTIONAL "
    "— omit it entirely. Do NOT validate, reformat, second-guess, or reject the "
    "values, even if they look like placeholders or invalid formats. After the "
    "tool returns, report the result."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fn_schema(tool_spec: dict[str, Any]):
    fields: dict[str, Any] = {}
    for p in tool_spec["params"]:
        if p["required"]:
            fields[p["name"]] = (str, ...)
        else:
            fields[p["name"]] = (Optional[str], None)
    return create_model(f"{tool_spec['name']}_Args", **fields)


def _build_tool(tool_spec: dict[str, Any], answer: str) -> FunctionTool:
    name = tool_spec["name"]

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
    session = json.loads(Path(os.environ["BENCH_SESSION_PATH"]).read_text())
    needle_answers = {t["needle"]: t["expected_answer"] for t in session["turns"]}

    tools = [
        _build_tool(t, needle_answers.get(t["name"], f"CALLED:{t['name']}"))
        for t in session["tools"]
    ]
    agent = FunctionAgent(tools=tools, llm=llm, system_prompt=_SYSTEM, verbose=False, timeout=None)

    # One ChatMemoryBuffer (huge limit, no silent trim) primed with the system
    # message, persisted across turns via a single reused Context.
    memory = ChatMemoryBuffer.from_defaults(
        token_limit=1_000_000,
        chat_history=[ChatMessage(role=MessageRole.SYSTEM, content=_SYSTEM)],
    )
    ctx = Context(workflow=agent)

    async def _run_all() -> tuple[list[str], list[str]]:
        await ctx.store.set("memory", memory)
        boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0
        answers_inner: list[str] = []
        for i, turn in enumerate(session["turns"]):
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    handler = agent.run(user_msg=turn["question"], ctx=ctx, max_iterations=12)
                    result = await handler  # type: ignore[misc]
                    if hasattr(result, "response"):
                        final_text = result.response.content or ""
                    else:
                        final_text = str(result)
                    answers_inner.append(str(final_text))
                    last_exc = None
                    break
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    msg = str(e)
                    status = getattr(e, "status_code", None) or getattr(
                        getattr(e, "response", None), "status_code", None
                    )
                    transient = (status is not None and 500 <= int(status) < 600) or (
                        "503" in msg or "overloaded" in msg.lower() or "unavailable" in msg.lower()
                    )
                    if transient and attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    break
            if last_exc is not None:
                answers_inner.append(f"[ERROR turn {i}: {type(last_exc).__name__}: {last_exc}]")
            boundaries.append(_now_iso())  # boundary AFTER this turn
        return answers_inner, boundaries

    answers, turn_boundaries = asyncio.run(_run_all())

    extras = {"turn_boundaries": turn_boundaries, "n_turns": len(session["turns"]), "answers": answers}
    return {"ok": True}, zero, extras
