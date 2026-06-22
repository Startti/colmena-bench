"""Task 5 — LangChain context-tax demo ("context scrubbing" hero demo).

Replays the fixed 10-turn conversation (``bench_common.scenario05.TURNS``) using
LangChain's idiomatic multi-turn chat: a growing message list with ``ChatOpenAI``
+ bound tools — the framework's DEFAULT memory.  Full history is re-sent each turn,
tool results (including the ~32KB base64 chart data URI) are retained in history
and NEVER trimmed.  This is the "competitor" baseline that Colmena's scrubber
eliminates.

Tool calling:
  We use ``llm.bind_tools([generate_chart_tool])`` which produces a bound
  ``_ChatModelBinding`` that still exposes ``.invoke(messages)``.  The returned
  ``AIMessage`` exposes ``.tool_calls`` as a list of dicts with keys
  ``id``, ``name``, ``args``.

Chart payload transport workaround:
  LiteLLM's Gemini translator auto-promotes any tool/message text starting with
  ``data:image/`` into a Gemini image part, which then rejects our synthetic PNG.
  We prefix the payload with ``[chart_data_uri]: `` so the string does NOT start
  with ``data:`` — the full ~32KB payload is still present as text, faithfully
  measuring the context tax.  (The CrewAI handler does exactly this.)

Span correlation:
  ``default_headers={"x-bench-run-id": args.run_id}`` on the ``ChatOpenAI`` object
  (set by ``build_llm``) ensures the proxy writes every span to
  ``proxy/spans/run-<run_id>.jsonl``.  We use the ``llm`` as-is from the factory
  (no re-bind needed) — just call ``.bind_tools()`` on it to add tool schemas.

Token accounting comes from the proxy spans (the orchestrator buckets spans by
``turn_boundaries`` timestamps), so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from bench_common import (
    CHART_TOOL_DESCRIPTION,
    CHART_TOOL_NAME,
    REPORT_TEXT,
    SYSTEM_MESSAGE,
    TURNS,
    RunnerArgs,
    generate_chart,
)


def _now_iso() -> str:
    """Return an ISO-8601 UTC timestamp ending in 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Tool definition (LangChain @tool decorator → StructuredTool)
# ---------------------------------------------------------------------------
@tool
def _generate_chart_tool(description: str) -> str:
    """Generate a chart image from a natural-language description. Returns the chart as a base64 PNG data URI."""  # noqa: E501
    return generate_chart(description)


# Override the name/description to match the bench_common constants so the
# system prompt's function name aligns with what we register.
_generate_chart_tool.name = CHART_TOOL_NAME
_generate_chart_tool.description = CHART_TOOL_DESCRIPTION


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    """Run all 10 turns and return (answers, usage, extras).

    Parameters
    ----------
    task_def:
        The loaded task YAML dict (unused beyond registry dispatch).
    llm:
        The ``ChatOpenAI`` instance built by ``build_llm`` — already routed
        through the proxy with the ``x-bench-run-id`` header set.
    args:
        Parsed runner arguments.

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
    # Bind the chart tool to the LLM (preserves base_url, api_key, headers).
    llm_with_tools = llm.bind_tools([_generate_chart_tool])

    # ------------------------------------------------------------------ #
    # Seed history                                                         #
    # ------------------------------------------------------------------ #
    messages: list[Any] = [
        SystemMessage(content=SYSTEM_MESSAGE),
        HumanMessage(content=f"Here is the report for this conversation:\n\n{REPORT_TEXT}"),
        AIMessage(content="Understood. I have the report and will answer your questions."),
    ]

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(TURNS):
        try:
            # ---------------------------------------------------------- #
            # Append user message and call the model                      #
            # ---------------------------------------------------------- #
            messages.append(HumanMessage(content=turn["message"]))
            ai_msg: AIMessage = llm_with_tools.invoke(messages)
            messages.append(ai_msg)

            # ---------------------------------------------------------- #
            # Handle tool calls if the model issued any                   #
            # ---------------------------------------------------------- #
            tool_calls = ai_msg.tool_calls or []
            if tool_calls:
                # Execute each tool call and append ToolMessage results.
                # The base64 data URI STAYS in the history — that is the
                # measured behavior (competitors accumulate it; Colmena does not).
                for tc in tool_calls:
                    try:
                        description = tc["args"].get("description", "")
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
                        ToolMessage(
                            content=chart_result,
                            tool_call_id=tc["id"],
                        )
                    )

                # Follow-up call to get the final text response after tool results
                final_msg: AIMessage = llm_with_tools.invoke(messages)
                messages.append(final_msg)
                final_text = final_msg.content or ""
            else:
                # Plain text response — no tool calls
                final_text = ai_msg.content or ""

            answers.append(str(final_text))

        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            err_text = f"[ERROR turn {i}: {type(e).__name__}: {e}]"
            answers.append(err_text)
            # Append a placeholder assistant message so history stays
            # structurally valid for subsequent turns.
            messages.append(AIMessage(content=err_text))
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, usage, extras
