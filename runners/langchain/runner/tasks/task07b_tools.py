"""Demo #7 v2 — LangChain MULTI-TURN many-tools handler.

Mirrors ``task07_tools`` (N ``StructuredTool``s built from a spec, each logging
its call and returning a deterministic answer, bound via ``llm.bind_tools``) but
replays a fixed multi-turn conversation like ``task05``: ONE growing message
list across all turns — LangChain's default memory — so all ~30 tool schemas are
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

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import create_model

from bench_common import RunnerArgs, scenario_tools

_MAX_ITERS = 6
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


def _invoke_with_retry(llm_with_tools: Any, messages: list[Any]) -> AIMessage:
    """One bound-LLM invoke with up to 3x retry on transient 5xx/503."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return llm_with_tools.invoke(messages)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            status = getattr(e, "status_code", None) or getattr(
                getattr(e, "response", None), "status_code", None
            )
            msg = str(e)
            transient = (status is not None and 500 <= int(status) < 600) or (
                "503" in msg or "overloaded" in msg.lower() or "unavailable" in msg.lower()
            )
            if transient and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_exc  # type: ignore[misc]


def _run_selector(llm: Any, tools: list, session: dict) -> tuple[Any, dict[str, int], dict[str, Any]]:
    """Multi-turn session driven by create_agent + LLMToolSelectorMiddleware.

    Each turn re-invokes the agent on the growing message list; the middleware
    picks the top-``max_tools`` relevant tools before the main model call, so only
    that subset's schemas are sent. Selector and main calls both go through the
    proxy, so cumulative-token accounting captures the real trade-off.
    """
    from langchain.agents import create_agent  # noqa: PLC0415
    from langchain.agents.middleware import tool_selection as _ts  # noqa: PLC0415
    from langchain.agents.middleware.tool_selection import LLMToolSelectorMiddleware  # noqa: PLC0415

    # The stock middleware builds its structured-output schema from a Union of
    # Literal[name] (pydantic emits `anyOf`/`const`), which gemini-2.5-flash via the
    # LiteLLM proxy does NOT strictly enforce — the selector returns descriptions or
    # hallucinated names, which the middleware rejects ("Model selected invalid
    # tools"). A flat JSON-Schema string `enum` over the same names IS enforced by
    # the same model (verified directly). Patch the schema builder to emit that flat
    # enum so LangChain's native selector actually works against this provider.
    class _FlatEnumSchema:
        def __init__(self, names):
            self._names = list(names)
        def json_schema(self):
            return {
                "title": "ToolSelection", "type": "object",
                "properties": {"tools": {"type": "array",
                    "items": {"type": "string", "enum": self._names}}},
                "required": ["tools"],
            }

    _ts._create_tool_selection_response = lambda tools: _FlatEnumSchema([t.name for t in tools])

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=_SYSTEM,
        middleware=[LLMToolSelectorMiddleware(model=llm, max_tools=5)],
    )

    messages: list[Any] = []
    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(session["turns"]):
        try:
            messages.append(HumanMessage(content=turn["question"]))
            result = agent.invoke({"messages": messages})
            messages = result["messages"]
            final_text = ""
            for m in reversed(messages):
                if isinstance(m, AIMessage) and m.content:
                    final_text = m.content if isinstance(m.content, str) else str(m.content)
                    break
            answers.append(str(final_text))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            err_text = f"[ERROR turn {i}: {type(e).__name__}: {e}]"
            answers.append(err_text)
            messages.append(AIMessage(content=err_text))
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {"turn_boundaries": turn_boundaries, "n_turns": len(session["turns"]), "answers": answers}
    return {"ok": True}, zero, extras


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
    by_name = {t.name: t for t in tools}

    # Tuned "selector" arm: LangChain's native LLMToolSelectorMiddleware pre-selects
    # a small relevant subset of tools before each model call (an extra selector LLM
    # call), so only those schemas are bound — the framework's native answer to a
    # large toolset. The trade-off (fewer schema tokens vs an extra call) is measured
    # in full because both calls route through the proxy.
    if os.environ.get("BENCH_LANGCHAIN_SELECTOR") == "1":
        return _run_selector(llm, tools, session)

    llm_with_tools = llm.bind_tools(tools)

    messages: list[Any] = [SystemMessage(content=_SYSTEM)]
    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(session["turns"]):
        try:
            messages.append(HumanMessage(content=turn["question"]))
            final_text = ""
            for _ in range(_MAX_ITERS):
                ai_msg: AIMessage = _invoke_with_retry(llm_with_tools, messages)
                messages.append(ai_msg)
                tool_calls = ai_msg.tool_calls or []
                if not tool_calls:
                    final_text = ai_msg.content or ""
                    break
                for tc in tool_calls:
                    tool = by_name.get(tc["name"])
                    try:
                        result = (
                            tool.invoke(tc["args"]) if tool else f"unknown tool {tc['name']}"
                        )
                    except Exception as e:  # noqa: BLE001 — surface to the agent
                        result = f"ERROR: {type(e).__name__}: {e}"
                    messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            answers.append(str(final_text))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            err_text = f"[ERROR turn {i}: {type(e).__name__}: {e}]"
            answers.append(err_text)
            messages.append(AIMessage(content=err_text))
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    extras = {"turn_boundaries": turn_boundaries, "n_turns": len(session["turns"]), "answers": answers}
    return {"ok": True}, zero, extras
