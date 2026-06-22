"""Task 5 — LlamaIndex context-tax demo ("context scrubbing" hero demo).

Replays the fixed 10-turn conversation (``bench_common.scenario05.TURNS``) using
LlamaIndex's idiomatic multi-turn chat with memory: a ``FunctionAgent`` (new
``AgentWorkflow``-based API, v0.14+) driven by a reused ``Context`` object that
stores a ``ChatMemoryBuffer`` across calls.

Memory model:
  ``BaseWorkflowAgent._init_context`` stores the ``ChatMemoryBuffer`` in
  ``ctx.store["memory"]`` on the first call.  Subsequent calls with the SAME
  ``ctx`` instance skip re-initialization (``ctx.store.get("memory") is not None``),
  so the full history — including the ~32KB base64 chart tool results — is retained
  and re-sent to the model on every turn.  Token limit is set to 1_000_000 to
  prevent any silent truncation; we are measuring the *untrimmed default* behavior.

Tool calling:
  A ``FunctionTool`` wrapping ``bench_common.generate_chart`` is registered with
  the agent.  The returned data URI is prefixed with ``[chart_data_uri]: `` so
  that LiteLLM's Gemini translator does NOT auto-promote the ``data:image/…``
  string to an inline image part (which Gemini rejects for our synthetic PNG).
  The full ~32KB payload stays in history as text, faithfully measuring the
  context-tax growth.

Async:
  ``FunctionAgent.run()`` returns a ``WorkflowHandler`` that is awaitable
  (implements ``__await__``).  We drive the entire turn loop inside a single
  ``asyncio.run()`` call for simplicity.

Span correlation:
  The ``OpenAILike`` instance built by ``build_llm`` already carries
  ``x-bench-run-id`` in its ``default_headers``; the proxy writes every span to
  ``proxy/spans/run-<run_id>.jsonl``.  Token accounting comes from those spans,
  so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import Context

from bench_common import (
    CHART_TOOL_DESCRIPTION,
    CHART_TOOL_NAME,
    REPORT_TEXT,
    SYSTEM_MESSAGE,
    TURNS,
    RunnerArgs,
    generate_chart as _generate_chart,
)


def _now_iso() -> str:
    """Return an ISO-8601 UTC timestamp ending in 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

def _chart_tool_fn(description: str) -> str:  # noqa: ARG001
    """Generate a chart — description is accepted but ignored (fixed payload)."""
    # Prefix with a label so LiteLLM's Gemini translator does NOT auto-convert
    # the data: URI to an image part (which Gemini would reject for our synthetic
    # PNG).  The full ~32KB payload is still present as text so the context-tax
    # growth is faithfully captured in token counts.
    return "[chart_data_uri]: " + _generate_chart("")


_chart_tool = FunctionTool.from_defaults(
    fn=_chart_tool_fn,
    name=CHART_TOOL_NAME,
    description=CHART_TOOL_DESCRIPTION,
)


# ---------------------------------------------------------------------------
# Async inner loop
# ---------------------------------------------------------------------------

async def _run_turns(agent: FunctionAgent, ctx: Context) -> list[str]:
    """Drive all 10 turns against the agent, returning one answer per turn."""
    answers: list[str] = []

    for i, turn in enumerate(TURNS):
        try:
            if i == 0:
                # Seed the report on the very first user message.  It enters the
                # ChatMemoryBuffer once and persists for the lifetime of ctx.
                user_text = (
                    f"Here is the report for this conversation:\n\n{REPORT_TEXT}"
                    f"\n\n{turn['message']}"
                )
            else:
                user_text = turn["message"]

            # ``agent.run()`` returns a WorkflowHandler that implements __await__.
            # Passing the SAME ctx object preserves the ChatMemoryBuffer stored
            # in ctx.store["memory"] across calls — this is the native LlamaIndex
            # multi-turn mechanism.
            handler = agent.run(user_msg=user_text, ctx=ctx)
            result = await handler  # type: ignore[misc]

            # result is an AgentOutput pydantic model; .response is a ChatMessage.
            if hasattr(result, "response"):
                final_text = result.response.content or ""
            else:
                final_text = str(result)

            answers.append(str(final_text))

        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            answers.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")

    return answers


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    """Run all 10 turns and return (answers, usage, extras).

    Parameters
    ----------
    task_def:
        Loaded task YAML dict (unused beyond registry dispatch).
    llm:
        ``OpenAILike`` instance built by ``build_llm`` — already routed through
        the proxy with the ``x-bench-run-id`` header set.
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
    # Build a ChatMemoryBuffer with a very high token limit so it never silently
    # truncates — we are measuring the default "keep everything" behavior.
    memory = ChatMemoryBuffer.from_defaults(
        token_limit=1_000_000,
        chat_history=[
            # Prime memory with the system message so it is present on every turn.
            ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_MESSAGE),
        ],
    )

    # Build the FunctionAgent.  The system_prompt here is also written into the
    # workflow setup; we rely on the seeded memory above for actual propagation.
    agent = FunctionAgent(
        tools=[_chart_tool],
        llm=llm,
        system_prompt=SYSTEM_MESSAGE,
        verbose=False,
        timeout=None,  # disable the 45-second default — turns with large context can take longer
    )

    # A single Context object that persists the ChatMemoryBuffer across all turns.
    ctx = Context(workflow=agent)

    # Pre-seed the memory into ctx.store so _init_context picks it up on turn 0
    # instead of creating a fresh default buffer (which would drop our SYSTEM
    # message seed).  We do this via a tiny sync helper that runs in the same
    # event loop as the main run.
    async def _seed_and_run() -> tuple[list[str], list[str]]:
        # Seed: store the primed memory buffer into the context store.
        await ctx.store.set("memory", memory)

        # Capture the "before turn 0" boundary, then run all turns with per-turn
        # boundaries captured via try/finally in the outer loop below.
        boundaries: list[str] = [_now_iso()]
        answers_inner: list[str] = []

        for i, turn in enumerate(TURNS):
            try:
                if i == 0:
                    user_text = (
                        f"Here is the report for this conversation:\n\n{REPORT_TEXT}"
                        f"\n\n{turn['message']}"
                    )
                else:
                    user_text = turn["message"]

                handler = agent.run(user_msg=user_text, ctx=ctx)
                result = await handler  # type: ignore[misc]

                if hasattr(result, "response"):
                    final_text = result.response.content or ""
                else:
                    final_text = str(result)

                answers_inner.append(str(final_text))

            except Exception as e:  # noqa: BLE001
                answers_inner.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")
            finally:
                boundaries.append(_now_iso())  # boundary AFTER this turn

        return answers_inner, boundaries

    answers, turn_boundaries = asyncio.run(_seed_and_run())

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, usage, extras
