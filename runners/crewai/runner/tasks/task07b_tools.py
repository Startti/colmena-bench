"""Demo #7 v2 — CrewAI MULTI-TURN many-tools handler.

Mirrors ``task07_tools`` (N dynamically-generated `@tool`s from a spec, each
logging its call and returning a deterministic answer) but replays a fixed
multi-turn conversation like ``task05``: it maintains ONE litellm message
history across all turns, re-sending all ~30 tool schemas every turn (the whole
point — competitors pay the full schema tax on every turn).

Call path: ``litellm.completion`` (direct), mirroring task05's rationale — we
need the full assistant message dict (tool_calls[].id) to maintain history and
do the tool round-trip ourselves.

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
from typing import Any

import litellm

from bench_common import RunnerArgs, scenario_tools

litellm.suppress_debug_info = True

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


def _build_tools_and_map(session: dict) -> tuple[list[dict], dict[str, str]]:
    """Return (OpenAI tool schemas, name->answer map)."""
    needle_answers = {t["needle"]: t["expected_answer"] for t in session["turns"]}
    answer_map = {
        t["name"]: needle_answers.get(t["name"], f"CALLED:{t['name']}")
        for t in session["tools"]
    }
    tools: list[dict] = []
    for t in session["tools"]:
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in t["params"]:
            ty = p["type"] if p["type"] != "array" else "string"
            props[p["name"]] = {"type": ty, "description": p["description"]}
            if p["required"]:
                required.append(p["name"])
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
        )
    return tools, answer_map


def _call_llm(messages: list[dict], tools: list[dict], args: RunnerArgs) -> Any:
    """One litellm completion routed through the proxy, with 503 retry."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return litellm.completion(
                model=f"openai/{args.model_alias}",
                base_url=args.proxy_base_url,
                api_key=os.environ.get(
                    "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
                ),
                messages=messages,
                tools=tools,
                temperature=0.0,
                extra_headers={"x-bench-run-id": args.run_id},
            )
        except Exception as e:  # noqa: BLE001
            last_exc = e
            status = getattr(e, "status_code", None)
            if status is not None and 500 <= int(status) < 600 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_exc  # type: ignore[misc]


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    zero = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    session = json.loads(Path(os.environ["BENCH_SESSION_PATH"]).read_text())
    tools, answer_map = _build_tools_and_map(session)

    messages: list[dict] = [{"role": "system", "content": _SYSTEM}]
    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(session["turns"]):
        try:
            messages.append({"role": "user", "content": turn["question"]})
            resp = _call_llm(messages, tools, args)
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []
            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
                for tc in tool_calls:
                    try:
                        tc_args = json.loads(tc.function.arguments or "{}")
                    except Exception:  # noqa: BLE001
                        tc_args = {}
                    passed = {k: v for k, v in tc_args.items() if v is not None}
                    scenario_tools.log_tool_call(tc.function.name, passed)
                    result = answer_map.get(tc.function.name, f"CALLED:{tc.function.name}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.function.name,
                            "content": result,
                        }
                    )
                resp2 = _call_llm(messages, tools, args)
                final_text = resp2.choices[0].message.content or ""
                messages.append({"role": "assistant", "content": final_text})
            else:
                final_text = msg.content or ""
                messages.append({"role": "assistant", "content": final_text})
            answers.append(final_text)
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            err_text = f"[ERROR turn {i}: {type(e).__name__}: {e}]"
            answers.append(err_text)
            messages.append({"role": "assistant", "content": err_text})
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    extras = {"turn_boundaries": turn_boundaries, "n_turns": len(session["turns"]), "answers": answers}
    return {"ok": True}, zero, extras
