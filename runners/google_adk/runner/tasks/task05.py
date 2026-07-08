"""Task 5 — Google ADK context-tax demo ("context scrubbing" hero demo).

Replays the fixed 10-turn conversation (``bench_common.scenario05.TURNS``) using
Google ADK's idiomatic multi-turn: an ``Agent`` (LlmAgent) driven by a ``Runner``
against a SINGLE reused ``Session``.  ADK re-sends the full session event history
each turn by default (no trimming), so the growing base64 chart payload stays in
context — exactly the "competitor" baseline that Colmena's scrubber eliminates.

Tool calling:
  A plain Python function ``generate_chart`` is registered as an ADK tool via the
  ``tools=`` list on the ``Agent``.  ADK auto-wraps plain callables via FunctionTool.

Chart payload transport workaround:
  LiteLLM's Gemini translator auto-promotes any tool return text starting with
  ``data:image/`` into a Gemini image part, which then rejects our synthetic PNG.
  We prefix the payload with ``[chart_data_uri]: `` (identical to the other 4
  competitor handlers) so the string does NOT start with ``data:``.  The full ~32KB
  payload is still present as text, faithfully measuring the context tax.

Token accounting comes from the proxy spans (the orchestrator buckets spans by
``turn_boundaries`` timestamps), so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from bench_common import (
    CHART_TOOL_DESCRIPTION,
    CHART_TOOL_NAME,
    REPORT_TEXT,
    SYSTEM_MESSAGE,
    TURNS,
    RunnerArgs,
    generate_chart as _generate_chart_asset,
)

_APP = "colmena_bench"
_USER = "bench_user"


def _now_iso() -> str:
    """Return an ISO-8601 UTC timestamp ending in 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Tool definition
# ADK auto-wraps plain Python callables; the function name and docstring
# become the tool name/description sent to the model.
# We define a wrapper here so the name matches CHART_TOOL_NAME exactly.
# ---------------------------------------------------------------------------
def generate_chart(description: str) -> str:
    """Generate a chart image from a natural-language description. Returns the chart as a base64 PNG data URI."""  # noqa: E501
    # Prefix prevents LiteLLM's Gemini translator from auto-converting the
    # data: URI into an inline_data image part (which Gemini rejects for our
    # synthetic PNG).  The full ~32KB payload stays as text — that is the
    # measured context tax.
    return "[chart_data_uri]: " + _generate_chart_asset(description)


# Patch the function name so ADK registers it under the bench_common constant.
generate_chart.__name__ = CHART_TOOL_NAME
generate_chart.__qualname__ = CHART_TOOL_NAME
generate_chart.__doc__ = CHART_TOOL_DESCRIPTION


# ---------------------------------------------------------------------------
# Tool-output-scrubbing variant (the "artifacts_scrub" deep steelman).
# Instead of returning the ~8 KB base64 blob into the conversation (where ADK
# re-sends it every subsequent turn), this hand-rolled tool stores the PNG bytes
# via ADK's native ArtifactService and returns only a short HANDLE. The blob never
# reaches the LLM context. This is the closest a determined ADK developer can get
# to Colmena's engine-default binary scrubber — but it is application code the
# developer must write in every tool, not a default. `tool_context` is auto-injected
# by ADK (by type annotation) and excluded from the schema the model sees, so the
# tool the model calls is identical to `generate_chart`.
# ---------------------------------------------------------------------------
async def generate_chart_scrub(description: str, tool_context: ToolContext) -> str:
    """Generate a chart image from a natural-language description. Returns the chart as a base64 PNG data URI."""  # noqa: E501
    data_uri = _generate_chart_asset(description)  # data:image/png;base64,<...>
    png_bytes = base64.b64decode(data_uri.split(",", 1)[1])
    n = int(tool_context.state.get("chart_count", 0)) + 1
    tool_context.state["chart_count"] = n
    filename = f"chart_{n}.png"
    await tool_context.save_artifact(
        filename=filename,
        artifact=types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
    )
    # Return only a short handle — the ~8 KB blob stays in the artifact store.
    return (
        f"Chart generated and stored as artifact '{filename}' (image/png). "
        "The chart is ready; confirm to the user in one short sentence."
    )


generate_chart_scrub.__name__ = CHART_TOOL_NAME
generate_chart_scrub.__qualname__ = CHART_TOOL_NAME
generate_chart_scrub.__doc__ = CHART_TOOL_DESCRIPTION


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    """Run all 10 turns and return (answers, usage, extras).

    Parameters
    ----------
    task_def:
        The loaded task YAML dict (unused beyond registry dispatch).
    llm:
        The ``LiteLlm`` instance built by ``build_llm`` — already routed
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
    answers, extras = asyncio.run(_run_all_turns(llm, args))
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answers, usage, extras


async def _run_all_turns(llm: Any, args: RunnerArgs) -> tuple[list[str], dict[str, Any]]:
    """Drive all 10 turns on a single persistent session.

    Three variants:
      default         — the report is pasted into turn 0 and re-sent in history
                        every turn; ``generate_chart`` returns the ~8 KB base64 blob
                        into context (the idiomatic ADK baseline; the context tax).
      artifacts       — the report is stored via ADK's native ArtifactService and
                        the agent gets the built-in ``load_artifacts`` tool, so the
                        DOC stays out of standing context. The chart blob still lands
                        in context (ADK has no default tool-output scrubbing).
      artifacts_scrub — the deep steelman: DOC via ``load_artifacts`` AND the
                        chart tool hand-rolled to ``save_artifact`` the PNG and
                        return a short handle, so the chart blob also stays out of
                        context. The closest ADK can get to Colmena's engine-default
                        scrubber — via per-tool application code.
    """
    use_doc_artifact = args.variant in ("artifacts", "artifacts_scrub")
    scrub_tool_output = args.variant == "artifacts_scrub"

    tools: list[Any] = [generate_chart_scrub if scrub_tool_output else generate_chart]
    if use_doc_artifact:
        from google.adk.tools import load_artifacts  # noqa: PLC0415
        tools.append(load_artifacts)

    agent = Agent(
        name="responder",
        model=llm,
        instruction=SYSTEM_MESSAGE,
        tools=tools,
    )
    runner = InMemoryRunner(agent=agent, app_name=_APP)

    # Create one session that will be reused across all 10 turns.
    # ADK re-sends the full event history from this session each turn.
    session_id = f"demo05_{args.run_id}"
    session = await runner.session_service.create_session(
        app_name=_APP,
        user_id=_USER,
        session_id=session_id,
    )

    if use_doc_artifact:
        # Store the report as a native artifact instead of putting it in context.
        await runner.artifact_service.save_artifact(
            app_name=_APP,
            user_id=_USER,
            session_id=session.id,
            filename="report.txt",
            artifact=types.Part(text=REPORT_TEXT),
        )

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(TURNS):
        try:
            # Turn 0: seed the report (pasted in default; referenced in artifacts).
            if i == 0 and use_doc_artifact:
                user_text = (
                    "A report for this conversation is stored as the artifact "
                    "'report.txt'. Call the load_artifacts tool to read it whenever "
                    "you need to answer a question about the report.\n\n"
                    f"{turn['message']}"
                )
            elif i == 0:
                user_text = (
                    f"Here is the report for this conversation:\n\n{REPORT_TEXT}\n\n"
                    f"{turn['message']}"
                )
            else:
                user_text = turn["message"]

            content = types.Content(role="user", parts=[types.Part(text=user_text)])
            final_text = await _run_turn(runner, session.id, content)
            answers.append(final_text)

        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            err_text = f"[ERROR turn {i}: {type(e).__name__}: {e}]"
            answers.append(err_text)
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, extras


async def _run_turn(runner: InMemoryRunner, session_id: str, content: types.Content) -> str:
    """Run one turn, drain the event stream, and return the final assistant text."""
    answer_parts: list[str] = []

    async for event in runner.run_async(
        user_id=_USER,
        session_id=session_id,
        new_message=content,
    ):
        # Collect text from final-response events only.
        if event.is_final_response():
            if getattr(event, "content", None) and getattr(event.content, "parts", None):
                for part in event.content.parts:
                    txt = getattr(part, "text", None)
                    if txt:
                        answer_parts.append(txt)

    return "".join(answer_parts).strip()
