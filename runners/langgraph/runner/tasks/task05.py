"""Task 5 — LangGraph context-tax demo ("context scrubbing" hero demo).

Replays the fixed 10-turn conversation (``bench_common.scenario05.TURNS``) using
LangGraph's idiomatic multi-turn: a compiled ``StateGraph`` built via
``create_react_agent`` with a ``MemorySaver`` checkpointer keyed by a stable
``thread_id``.

The framework's DEFAULT memory: the checkpointer persists the full message history
(including retained tool outputs / ~32KB base64 chart data URI) across turns.
Nothing is trimmed or scrubbed — that is the measured behavior.

Tool calling:
  A LangChain ``@tool``-decorated function is bound to the LLM via the agent
  builder.  When the model issues a tool call the ToolNode inside the agent
  graph executes it and the ToolMessage (with the prefixed ~32KB payload) is
  written back into the checkpoint.

Chart payload transport workaround:
  LiteLLM's Gemini translator auto-promotes any string starting with
  ``data:image/`` into a Gemini image part (which then rejects our synthetic
  PNG).  We prefix the payload with ``[chart_data_uri]: `` so it does NOT start
  with ``data:`` — the full ~32KB payload is still present as text, faithfully
  measuring the context tax.

Span correlation:
  The ``ChatOpenAI`` instance built by ``build_llm`` already carries the
  ``x-bench-run-id`` header; we use it as-is.  Token accounting comes from
  proxy spans bucketed by ``turn_boundaries``, so ``usage`` is all zeros.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

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
# Tool definition
# ---------------------------------------------------------------------------

@tool
def _generate_chart_tool(description: str) -> str:
    """Generate a chart image from a natural-language description. Returns the chart as a base64 PNG data URI."""  # noqa: E501
    # Prefix so LiteLLM's Gemini translator does NOT auto-convert data: URIs.
    return "[chart_data_uri]: " + generate_chart(description)


# Override name/description to match bench_common constants so the system
# prompt's function name aligns with what we register.
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
    # ------------------------------------------------------------------ #
    # Build the compiled graph with a MemorySaver checkpointer            #
    # ------------------------------------------------------------------ #
    saver = MemorySaver()
    # Pass the system message via the `prompt` kwarg so create_react_agent
    # prepends it to every invocation automatically.
    agent = create_react_agent(
        llm,
        [_generate_chart_tool],
        prompt=SystemMessage(content=SYSTEM_MESSAGE),
        checkpointer=saver,
    )

    # Stable thread_id so every turn's invoke shares the same checkpoint.
    thread_id = f"demo05_{args.run_id}"
    config = {"configurable": {"thread_id": thread_id}}

    # ------------------------------------------------------------------ #
    # Seed: inject the report on turn 0 as a prefix to the first message  #
    # ------------------------------------------------------------------ #
    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(TURNS):
        try:
            if i == 0:
                # Prepend the report to the first user turn so it enters the
                # checkpoint once and persists across all subsequent turns.
                user_text = (
                    f"Here is the report for this conversation:\n\n{REPORT_TEXT}"
                    f"\n\n{turn['message']}"
                )
            else:
                user_text = turn["message"]

            result = agent.invoke(
                {"messages": [HumanMessage(content=user_text)]},
                config=config,
            )

            # The last message in the state is the final AIMessage text.
            last_msg = result["messages"][-1]
            if isinstance(last_msg, AIMessage):
                final_text = last_msg.content or ""
            else:
                final_text = str(last_msg)

            answers.append(str(final_text))

        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            err_text = f"[ERROR turn {i}: {type(e).__name__}: {e}]"
            answers.append(err_text)
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, usage, extras
