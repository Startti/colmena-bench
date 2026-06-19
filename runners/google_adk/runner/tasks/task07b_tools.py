"""Demo #7 v2 — Google ADK MULTI-TURN many-tools handler.

Mirrors ``task07_tools`` (N plain Python callables with dynamic per-spec
signatures registered as ADK tools, each logging its call and returning a
deterministic answer) but replays a fixed multi-turn conversation like
``task05``: an ``Agent`` driven by a single reused ADK ``Session`` so the full
event history — and all ~30 tool schemas — is re-sent every turn (the whole
point — competitors pay the full schema tax).

The needle varies per turn, so we precompute a name->answer map: a tool that is
some turn's needle returns that turn's ``expected_answer``; every other tool
returns ``CALLED:<name>``. Token accounting is via proxy spans bucketed by
``extras.turn_boundaries`` (one before turn 0 + one after each turn).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from bench_common import RunnerArgs, scenario_tools

_APP = "colmena_bench"
_USER = "bench_user"
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


def _build_fn(tool_spec: dict[str, Any], answer: str):
    name = tool_spec["name"]

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


async def _run_turn(runner: InMemoryRunner, session_id: str, content: types.Content) -> str:
    """One turn with up to 3x retry on transient 5xx/503; returns final text."""
    last_exc: Exception | None = None
    for attempt in range(3):
        answer_parts: list[str] = []
        try:
            async for event in runner.run_async(
                user_id=_USER, session_id=session_id, new_message=content
            ):
                if event.is_final_response():
                    if getattr(event, "content", None) and getattr(event.content, "parts", None):
                        for part in event.content.parts:
                            txt = getattr(part, "text", None)
                            if txt:
                                answer_parts.append(txt)
            return "".join(answer_parts).strip()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            msg = str(e)
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            transient = (
                (status is not None and str(status) in ("500", "502", "503", "504"))
                or "503" in msg
                or "overloaded" in msg.lower()
                or "unavailable" in msg.lower()
            )
            if transient and attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_exc  # type: ignore[misc]


async def _run_all(llm: Any, args: RunnerArgs, session: dict) -> tuple[list[str], list[str]]:
    needle_answers = {t["needle"]: t["expected_answer"] for t in session["turns"]}
    tools = [
        _build_fn(t, needle_answers.get(t["name"], f"CALLED:{t['name']}"))
        for t in session["tools"]
    ]
    agent = Agent(name="tool_dispatch_agent", model=llm, instruction=_SYSTEM, tools=tools)
    runner = InMemoryRunner(agent=agent, app_name=_APP)
    adk_session = await runner.session_service.create_session(
        app_name=_APP, user_id=_USER, session_id=f"tools7b_{args.run_id}"
    )

    answers: list[str] = []
    boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0
    for i, turn in enumerate(session["turns"]):
        try:
            content = types.Content(role="user", parts=[types.Part(text=turn["question"])])
            answers.append(await _run_turn(runner, adk_session.id, content))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            answers.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")
        finally:
            boundaries.append(_now_iso())  # boundary AFTER this turn
    return answers, boundaries


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    session = json.loads(Path(os.environ["BENCH_SESSION_PATH"]).read_text())
    answers, turn_boundaries = asyncio.run(_run_all(llm, args, session))
    extras = {"turn_boundaries": turn_boundaries, "n_turns": len(session["turns"]), "answers": answers}
    return {"ok": True}, zero, extras
