"""Task 5 — CrewAI context-tax demo ("context scrubbing" hero demo).

Replays the fixed 10-turn conversation (``bench_common.scenario05.TURNS``) in a
manual multi-turn loop, accumulating the FULL message history each turn — system
prompt, report preamble, all assistant replies, and crucially the raw ~32KB
base64 data URI returned by ``generate_chart`` — so the proxy spans clearly
show per-call input tokens GROWING across chart turns.  This is the "competitor"
baseline that Colmena's scrubber eliminates.

Call path chosen: ``litellm.completion`` (direct)
Why NOT ``crewai.LLM.call``:
  ``crewai.LLM.call(messages, tools=...)`` returns either a plain ``str`` (text
  response) or a raw ``list[ChatCompletionDeltaToolCall]`` (tool-call response),
  never the full ``ModelResponse``.  To maintain the message history ourselves we
  need the complete assistant message dict — including ``tool_calls[].id`` for the
  ``tool_call_id`` round-trip — which only the raw litellm response exposes.
  litellm is already present in the CrewAI venv (it IS the transport layer for
  crewai.LLM), so this adds no new dependency and all proxy routing/span
  correlation is replicated faithfully via the same ``model``, ``base_url``,
  ``api_key``, and ``extra_headers`` that ``build_llm`` would pass.

Span correlation:
  ``extra_headers={"x-bench-run-id": args.run_id}`` ensures the proxy writes
  every span to ``proxy/spans/run-<run_id>.jsonl`` (see proxy/spans_callback.py).

Token accounting comes from the proxy spans (the orchestrator buckets spans by
``turn_boundaries`` timestamps), so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import litellm

from bench_common import (
    RunnerArgs,
    REPORT_TEXT,
    TURNS,
    SYSTEM_MESSAGE,
    CHART_TOOL_NAME,
    CHART_TOOL_DESCRIPTION,
    generate_chart,
)

# Suppress litellm's noisy debug output
litellm.suppress_debug_info = True


def _now_iso() -> str:
    """Return an ISO-8601 UTC timestamp ending in 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# OpenAI-compatible function-tool schema for generate_chart
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": CHART_TOOL_NAME,
            "description": CHART_TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Natural-language description of the chart to generate.",
                    }
                },
                "required": ["description"],
            },
        },
    }
]


def _call_llm(messages: list[dict], args: RunnerArgs) -> Any:
    """Make one litellm completion call routed through the proxy."""
    return litellm.completion(
        model=f"openai/{args.model_alias}",
        base_url=args.proxy_base_url,
        api_key=os.environ.get(
            "LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod"
        ),
        messages=messages,
        tools=_TOOLS,
        temperature=0.0,
        extra_headers={"x-bench-run-id": args.run_id},
    )


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    """Run all 10 turns and return (answers, usage, extras).

    ``llm`` is the ``crewai.LLM`` object built by ``build_llm``.  We do not use
    it directly (see module docstring), but we extract nothing from it — all
    routing params come from ``args``.

    Returns
    -------
    answers
        List of 10 strings — one final text answer per turn.
    usage
        All zeros; token accounting is done via proxy spans.
    extras
        ``turn_boundaries``: 11 ISO-8601 UTC timestamps (one before turn 0,
        one after each of the 10 turns).
        ``turn_types``: list of the ``type`` field for each turn in TURNS.
    """
    # ------------------------------------------------------------------ #
    # Seed history                                                         #
    # ------------------------------------------------------------------ #
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {
            "role": "user",
            "content": f"Here is the report for this conversation:\n\n{REPORT_TEXT}",
        },
        {
            "role": "assistant",
            "content": "Understood. I have the report and will answer your questions.",
        },
    ]

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(TURNS):
        try:
            # ---------------------------------------------------------- #
            # Append user message and call the model                      #
            # ---------------------------------------------------------- #
            messages.append({"role": "user", "content": turn["message"]})
            resp = _call_llm(messages, args)
            msg = resp.choices[0].message

            # ---------------------------------------------------------- #
            # Handle tool calls if the model issued any                   #
            # ---------------------------------------------------------- #
            tool_calls = msg.tool_calls or []
            if tool_calls:
                # Append the assistant message WITH tool_calls so the
                # history is well-formed for the follow-up call.
                assistant_msg: dict[str, Any] = {
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
                messages.append(assistant_msg)

                # Execute each tool call and append results.
                # The base64 data URI STAYS in the history — that is the
                # measured behavior (competitors accumulate it; Colmena does not).
                for tc in tool_calls:
                    try:
                        tc_args = json.loads(tc.function.arguments or "{}")
                        description = tc_args.get("description", "")
                        chart_data_uri = generate_chart(description)
                        # Prefix with a label so that LiteLLM's Gemini translator
                        # does NOT auto-convert the data: URI to an inline_data
                        # image part (which Gemini would reject for a synthetic
                        # blob).  The prefix character '[' makes the string NOT
                        # start with "data:" — see litellm factory.py line ~1521.
                        # The full ~32KB payload is still present as text so the
                        # context-tax growth is faithfully captured in token counts.
                        chart_result = f"[chart_data_uri]: {chart_data_uri}"
                    except Exception as e:  # noqa: BLE001
                        chart_result = f"[tool error: {e}]"

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.function.name,
                            "content": chart_result,
                        }
                    )

                # Follow-up call to get the final text response
                resp2 = _call_llm(messages, args)
                msg2 = resp2.choices[0].message
                final_text = msg2.content or ""
                messages.append({"role": "assistant", "content": final_text})
            else:
                # Plain text response — no tool calls
                final_text = msg.content or ""
                messages.append({"role": "assistant", "content": final_text})

            answers.append(final_text)

        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            err_text = f"[ERROR turn {i}: {type(e).__name__}: {e}]"
            answers.append(err_text)
            # Append a placeholder assistant message so history stays
            # structurally valid for subsequent turns.
            messages.append({"role": "assistant", "content": err_text})
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, usage, extras
