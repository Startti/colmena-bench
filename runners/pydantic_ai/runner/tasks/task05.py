"""Task 5 — Pydantic AI context-tax demo (the "context scrubbing" competitor arm).

Replays the fixed 10-turn conversation (``bench_common.TURNS``) with Pydantic AI's
idiomatic multi-turn pattern: each turn calls ``agent.run_sync(msg,
message_history=...)`` and feeds the FULL returned message list back into the next
turn. That is the framework's default memory — the whole history, including the
~32 KB base64 chart tool-return, is re-sent every turn and never trimmed. This is
the competitor baseline that Colmena's binary scrubber eliminates.

Seeding: the report is planted as a pre-turn-0 exchange built directly from
``ModelRequest``/``ModelResponse`` (no LLM call), matching how the LangChain runner
seeds a static ``HumanMessage``/``AIMessage`` pair. The system prompt is set on the
``Agent``.

Chart payload transport workaround: LiteLLM's Gemini translator auto-promotes any
tool/message text starting with ``data:image/`` into a Gemini image part (which it
then rejects for a synthetic PNG). We prefix the payload with ``[chart_data_uri]: ``
so it does NOT start with ``data:`` — the full ~32 KB is still present as text, so
the context-tax growth is faithfully measured. (Every other runner does this.)

Token accounting is via proxy spans bucketed by ``extras.turn_boundaries``; the
returned ``usage`` is all zeros by contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from bench_common import (
    CHART_TOOL_DESCRIPTION,
    REPORT_TEXT,
    SYSTEM_MESSAGE,
    TURNS,
    RunnerArgs,
    generate_chart as _generate_chart,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(
    task_def: dict[str, Any], model: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    agent = Agent(
        model,
        system_prompt=SYSTEM_MESSAGE,
        model_settings={"temperature": 0.0},
    )

    # The tool name doubles as CHART_TOOL_NAME ("generate_chart"); its docstring is
    # CHART_TOOL_DESCRIPTION so the schema the model sees matches the other runners.
    @agent.tool_plain
    def generate_chart(description: str) -> str:
        return f"[chart_data_uri]: {_generate_chart(description)}"

    generate_chart.__doc__ = CHART_TOOL_DESCRIPTION

    # Seed the report as a pre-turn-0 exchange (no LLM call), mirroring the other
    # runners' static system + report + acknowledgement seed.
    history: list[Any] = [
        ModelRequest(parts=[
            UserPromptPart(content=f"Here is the report for this conversation:\n\n{REPORT_TEXT}")
        ]),
        ModelResponse(parts=[
            TextPart(content="Understood. I have the report and will answer your questions.")
        ]),
    ]

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(TURNS):
        try:
            result = agent.run_sync(turn["message"], message_history=history)
            history = result.all_messages()  # full verbatim history -> next turn
            answers.append(str(getattr(result, "output", "") or ""))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            answers.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, usage, extras
