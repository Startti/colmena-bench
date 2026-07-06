"""Task 5 — OpenAI Agents SDK context-tax demo (competitor arm).

Replays the fixed 10-turn conversation (``bench_common.TURNS``) with the Agents
SDK's idiomatic multi-turn pattern: each turn runs ``Runner.run_sync`` on the FULL
prior input list (``result.to_input_list()``) plus the new user message — the whole
verbatim history, including the ~32 KB base64 chart tool-return, is re-sent every
turn (the competitor baseline; Colmena's scrubber eliminates it).

The report is seeded as a pre-turn-0 user+assistant pair in the initial input list
(no LLM call). The ``[chart_data_uri]:`` prefix avoids LiteLLM's Gemini image
auto-promotion. Token accounting is via proxy spans bucketed by
``extras.turn_boundaries``; the returned ``usage`` is all zeros by contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents import Agent, ModelSettings, Runner, function_tool

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


@function_tool
def generate_chart(description: str) -> str:
    """Generate a chart image from a natural-language description. Returns the chart as a base64 PNG data URI."""  # noqa: E501
    return f"[chart_data_uri]: {_generate_chart(description)}"


def run(
    task_def: dict[str, Any], model: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    # CHART_TOOL_DESCRIPTION mirrors the docstring above so the schema matches the
    # other runners; reference it so a drift is caught in review.
    assert CHART_TOOL_DESCRIPTION  # noqa: S101

    agent = Agent(
        name="ReportAnalyst",
        instructions=SYSTEM_MESSAGE,
        tools=[generate_chart],
        model=model,
        model_settings=ModelSettings(temperature=0.0),
    )

    # Seed the report as a pre-turn-0 exchange (no LLM call).
    input_list: list[Any] = [
        {"role": "user", "content": f"Here is the report for this conversation:\n\n{REPORT_TEXT}"},
        {"role": "assistant", "content": "Understood. I have the report and will answer your questions."},
    ]

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(TURNS):
        try:
            input_list = input_list + [{"role": "user", "content": turn["message"]}]
            result = Runner.run_sync(agent, input_list)
            input_list = result.to_input_list()  # full verbatim history -> next turn
            answers.append(str(result.final_output or ""))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            answers.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {"turn_boundaries": turn_boundaries, "turn_types": [t["type"] for t in TURNS]}
    return answers, usage, extras
