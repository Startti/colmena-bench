"""Task 6 — Google ADK refund agent (Demo #4): native tool-calling, DIY rest.

The HONEST per-feature comparison for Google ADK. ADK is an agent framework with
strong native tool-calling (Agent + FunctionTool + Runner event loop), but it has
no native critic-retry-with-feedback, no native outbound tool-result masking, and
no durable cross-process suspend/resume usable for a two-process HITL interrupt.
Where ADK ships a real primitive we USE it; everything else is hand-rolled.

Per-feature assessment for Google ADK:

1. graph / orchestration — DIY. ADK has no graph DSL; the pipeline
   (draft → confirm → hitl → router) is an imperative Python driver. (ADK does
   ship ``SequentialAgent``/``LoopAgent`` workflow agents, but they cannot
   express the rule-checked retry-with-feedback + masked-tool + cross-process
   suspend this demo needs without the same hand-rolled glue, so we keep the
   honest imperative driver like the other code-first frameworks.)

2. critic_retry — DIY. ADK has no native rule-check-and-reprompt-with-feedback.
   We drive an explicit loop: run a no-tool Agent turn, rule-check via
   ``scenario_refund.policy_violation``, re-prompt with feedback, count retries.

3. confirm w/ masked payment tool — tool-calling is NATIVE (a plain Python
   callable is auto-wrapped as a ``FunctionTool``; ADK loops it internally), but
   ADK has NO native OUTBOUND tool-result masking. The ``payment_lookup`` result
   carries the secret in ``auth_token``; we hand-scrub the field + secret
   substring INSIDE the tool wrapper BEFORE it re-enters the LLM context /
   reaches the proxy. This DIY scrub is the masking cost. (Colmena: ``secure:
   true`` on the node, zero user code.) The confirm Agent runs through the proxy
   with the scrubbed result so the masking audit is meaningful.

4. hitl_durable (cross-process) — DIY. FINDING: ADK's runtime HITL primitive is
   ``LongRunningFunctionTool``, whose paused tool call is resumed by feeding a
   ``FunctionResponse`` back into the SAME ``Runner`` instance — it is an
   in-process suspend, not a checkpoint a fresh process can rehydrate mid-run.
   ADK does ship persistent *session* services (``DatabaseSessionService``,
   ``VertexAiSessionService``, ``SqliteSessionService``) that durably store the
   conversation EVENT history, but they persist transcript events, not a
   resumable mid-execution checkpoint of a suspended agent run; reconstructing a
   paused ``LongRunningFunctionTool`` in a second process from event history is
   impractical and not a supported resume path. (``InMemoryRunner`` /
   ``InMemorySessionService`` is in-process only and would not survive a restart
   at all.) So for an honest two-process interrupt/resume we hand-roll it: phase 1
   persists state to a ``.state`` file and returns; phase 2 (a separate process)
   loads it and finishes — identical to crewai/langchain/llamaindex.

5. router — DIY. A keyword classifier maps the human's free-text answer to
   approve/reject/escalate (same ``classify_intent`` helper pattern as the other
   handlers). (Colmena: a ``router`` node.)

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
Token accounting is via proxy spans, so ``usage`` is all zeros by contract.

Two-phase contract (matches the driver):
- Phase 1 (``args.resume_state is None``): draft(+critic) + confirm-with-masked-
  tool; persist state to ``Path(str(args.output)+".state")``; return
  ``({"decision": None}, zero_usage, {"suspended": True})``.
- Phase 2 (``args.resume_state`` set): load state, classify
  ``args.resume_answer or CANONICAL_HUMAN_ANSWER``, return
  ``(state["answer"], zero_usage, {"final_intent": intent, "retries": retries})``.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from bench_common import RunnerArgs, extract_answer_dict, scenario_refund

_MAX_RETRIES = 3
_APPROVE_WORDS = ("approve", "yes", "ok", "okay", "go ahead", "confirm", "agree")
_REJECT_WORDS = ("reject", "deny", "no", "decline", "refuse")
_ESCALATE_WORDS = ("escalate", "manager", "supervisor", "review", "higher")

_APP = "colmena_bench"
_USER = "bench_user"


def _state_path(args: RunnerArgs) -> Path:
    return Path(str(args.output) + ".state")


def _zero_usage() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}


def classify_intent(answer: str) -> str:
    """Map a human's free-text approval answer to approve/reject/escalate.

    Pure + deterministic so it is unit-testable (the live LLM steps are not).
    Escalate and reject are checked before approve because phrases like
    "escalate, do not approve" contain approve-ish tokens. Matching is on word
    boundaries so "no" does not fire inside "not sure".
    """
    text = (answer or "").lower()

    def has(words: tuple[str, ...]) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)

    if has(_ESCALATE_WORDS):
        return "escalate"
    if has(_REJECT_WORDS):
        return "reject"
    if has(_APPROVE_WORDS):
        return "approve"
    return "escalate"  # ambiguous -> safest (human-review) branch


async def _run_agent_turn(agent: Agent, session_suffix: str, run_id: str, prompt: str) -> str:
    """Run ONE prompt through an Agent and drain the event stream for final text.

    A fresh InMemoryRunner + session per call keeps the draft/confirm turns
    isolated (no shared history); ADK loops any registered tool internally until
    the model returns its final answer.
    """
    runner = InMemoryRunner(agent=agent, app_name=_APP)
    session_id = f"{session_suffix}_{run_id}"
    session = await runner.session_service.create_session(
        app_name=_APP, user_id=_USER, session_id=session_id
    )
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    answer_parts: list[str] = []
    async for event in runner.run_async(
        user_id=_USER, session_id=session.id, new_message=content
    ):
        if event.is_final_response():
            if getattr(event, "content", None) and getattr(event.content, "parts", None):
                for part in event.content.parts:
                    txt = getattr(part, "text", None)
                    if txt:
                        answer_parts.append(txt)
    return "".join(answer_parts).strip()


def _draft_with_critic(llm: Any, base_prompt: str, run_id: str) -> tuple[dict[str, Any], int]:
    """LLM drafts a refund decision; rule-check it and re-prompt on violation.

    DIY critic-retry: ADK has no native rule-check-and-reprompt. Returns
    (decision_dict, retries); ``retries`` counts re-prompts after the first draft
    (0 means the first draft was already compliant).
    """
    instruction = (
        f"{base_prompt}\n\nCustomer: {scenario_refund.CUSTOMER_MESSAGE}\n"
        f"Requested amount: {scenario_refund.REQUEST['amount']} USD\n"
        f"Policy: {scenario_refund.POLICY_TEXT}\n\n"
        'Respond with ONLY a JSON object: '
        '{"decision": "approve|partial|reject|escalate", "amount": <number>, '
        '"justification": "<text>"}.'
    )
    agent = Agent(
        name="refund_drafter",
        model=llm,
        instruction="You are a refund support agent. Decide refunds strictly per policy.",
    )
    feedback = ""
    decision: dict[str, Any] = {}
    for attempt in range(_MAX_RETRIES + 1):
        prompt = instruction + (
            f"\n\nYour previous draft was rejected: {feedback}\n"
            "Fix it and respect the policy." if feedback else ""
        )
        raw = asyncio.run(_run_agent_turn(agent, f"t6draft{attempt}", run_id, prompt))
        decision = extract_answer_dict(str(raw))
        if not scenario_refund.policy_violation(decision):
            return decision, attempt
        feedback = (
            f"You chose decision={decision.get('decision')} amount={decision.get('amount')}, "
            "but a refund above 100 USD must be 'partial' (<=100) or 'escalate' — "
            "never a full 'approve' over 100."
        )
    return decision, _MAX_RETRIES


def _confirm_with_masked_tool(llm: Any, decision: dict[str, Any], run_id: str) -> str:
    """Confirm the decision via an Agent that calls a payment tool whose result is
    SCRUBBED of the secret before it re-enters the LLM context.

    Tool-calling is native (the callable is auto-wrapped as a FunctionTool and ADK
    loops it internally), but ADK has NO native outbound masking: the
    ``payment_lookup`` result carries the secret in ``auth_token``. We scrub the
    field + secret substring INSIDE the wrapper before returning it, so the secret
    never reaches the LLM context or the proxy. The masking audit
    (proxy/spans/mask-<run_id>.json) verifies the secret never reached the proxy.
    """

    def run_payment(order_id: str) -> str:
        """Look up an order in the payment gateway. Returns order status info."""
        result = scenario_refund.payment_lookup(order_id, scenario_refund.SECRET)
        # DIY outbound masking: drop the secret field, then defensively scrub the
        # secret substring from anything that remains, before it leaves the tool.
        result.pop("auth_token", None)
        return json.dumps(result).replace(scenario_refund.SECRET, "[REDACTED]")

    run_payment.__name__ = "run_payment"
    run_payment.__qualname__ = "run_payment"

    agent = Agent(
        name="refund_confirmer",
        model=llm,
        instruction="A payments agent that confirms refunds and never exposes credentials.",
        tools=[run_payment],
    )
    prompt = (
        f"Look up order {scenario_refund.REQUEST['order_id']} with the run_payment "
        f"tool, then write ONE line confirming this refund decision: "
        f"{json.dumps(decision)}. Do not reveal any credentials."
    )
    return asyncio.run(_run_agent_turn(agent, "t6confirm", run_id, prompt))


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    # ---- Phase 2: rehydrate persisted state and finish (router only) ---------
    if args.resume_state is not None:
        state = json.loads(Path(args.resume_state).read_text())
        human_answer = args.resume_answer or scenario_refund.CANONICAL_HUMAN_ANSWER
        intent = classify_intent(human_answer)
        return (
            state["answer"],
            _zero_usage(),
            {"final_intent": intent, "retries": state["retries"]},
        )

    # ---- Phase 1: draft (+critic retry) + confirm w/ masked tool, then suspend
    decision, retries = _draft_with_critic(llm, task_def["prompt"], args.run_id)
    # The confirm call MUST go through the proxy with the scrubbed tool result so
    # the masking audit is meaningful (it scans this call's messages for the secret).
    _confirm_with_masked_tool(llm, decision, args.run_id)

    _state_path(args).write_text(
        json.dumps({"answer": decision, "retries": retries}, indent=2)
    )
    return {"decision": None}, _zero_usage(), {"suspended": True}
