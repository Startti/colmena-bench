"""Demo #7 v2 — LangGraph MULTI-TURN many-tools handler.

Mirrors ``task07_tools`` (N ``StructuredTool``s built from a spec, each logging
its call and returning a deterministic answer, wired into ``create_react_agent``)
but replays a fixed multi-turn conversation like ``task05``: a compiled
``StateGraph`` with a ``MemorySaver`` checkpointer keyed by a stable
``thread_id``, invoked once PER TURN. The checkpointer persists the full message
history across turns — LangGraph's default memory — so all ~30 tool schemas are
re-sent every turn (the whole point — competitors pay the full schema tax).

The needle varies per turn, so we precompute a name->answer map: a tool that is
some turn's needle returns that turn's ``expected_answer``; every other tool
returns ``CALLED:<name>``. Token accounting is via proxy spans bucketed by
``extras.turn_boundaries`` (one before turn 0 + one after each turn).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import create_model

from bench_common import RunnerArgs, scenario_tools

_RECURSION_LIMIT = 50
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


def _args_model(tool_spec: dict[str, Any]):
    fields: dict[str, Any] = {}
    for p in tool_spec["params"]:
        if p["required"]:
            fields[p["name"]] = (str, ...)
        else:
            fields[p["name"]] = (Optional[str], None)
    return create_model(f"{tool_spec['name']}_Args", **fields)


def _build_tool(tool_spec: dict[str, Any], answer: str) -> StructuredTool:
    name = tool_spec["name"]

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
    session = json.loads(Path(os.environ["BENCH_SESSION_PATH"]).read_text())
    needle_answers = {t["needle"]: t["expected_answer"] for t in session["turns"]}

    tools = [
        _build_tool(t, needle_answers.get(t["name"], f"CALLED:{t['name']}"))
        for t in session["tools"]
    ]
    saver = MemorySaver()
    agent = create_react_agent(
        llm, tools, prompt=SystemMessage(content=_SYSTEM), checkpointer=saver
    )
    config = {"configurable": {"thread_id": f"tools7b_{args.run_id}"}, "recursion_limit": _RECURSION_LIMIT}

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(session["turns"]):
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                result = agent.invoke(
                    {"messages": [HumanMessage(content=turn["question"])]}, config=config
                )
                last = result["messages"][-1]
                final_text = last.content if isinstance(last, AIMessage) else str(last)
                answers.append(str(final_text))
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
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
        if last_exc is not None:
            answers.append(f"[ERROR turn {i}: {type(last_exc).__name__}: {last_exc}]")
        turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    extras = {"turn_boundaries": turn_boundaries, "n_turns": len(session["turns"]), "answers": answers}
    return {"ok": True}, zero, extras
