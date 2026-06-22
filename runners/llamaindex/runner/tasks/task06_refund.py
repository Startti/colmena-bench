"""Task 6 — LlamaIndex refund agent (Demo #4): hand-rolled HITL + critic + masking.

This is the IMPERATIVE, hand-rolled counterpart to Colmena's declarative refund
DAG, in plain LlamaIndex idiom. It implements the SAME agent as the CrewAI and
LangChain handlers (runners/{crewai,langchain}/runner/tasks/task06_refund.py).
Every production capability Colmena expresses as a node + config flag is
hand-coded here, and the extra Python is the node-vs-code cost we measure.

What LlamaIndex gives us natively vs. what we hand-roll:

1. draft + critic-retry  — hand-rolled. LlamaIndex has no built-in critic /
   guarded-retry primitive; we drive an explicit loop over ``llm.chat`` with
   ``ChatMessage`` turns, rule-check via ``scenario_refund.policy_violation``,
   and re-prompt with feedback (max 3 retries, counted).

2. confirm w/ masked payment tool — tool-calling is native (``FunctionAgent`` +
   ``FunctionTool``, the AgentWorkflow API, mirroring task04_expert), but
   LlamaIndex has NO native OUTBOUND tool-result masking. The ``FunctionTool``
   return value is fed straight back into the LLM context (and the proxy sees
   it). We hand-wrap the tool to SCRUB the secret ``auth_token`` out of the
   ``payment_lookup`` result BEFORE it is returned — drop the field and
   defensively replace the secret substring. This DIY scrub is the masking cost.
   Colmena does it with ``secure: true`` on the node (zero user code).

3. HITL approval (durable, cross-process) — hand-rolled. LlamaIndex's native
   human-in-the-loop is an in-process Workflow event: a step emits an
   ``InputRequiredEvent`` and the caller resumes with a ``HumanResponseEvent``
   on the SAME running ``handler`` / event stream (see
   https://docs.llamaindex.ai/en/stable/understanding/agent/human_in_the_loop/
   — "Human in the loop"). FINDING: that primitive is in-process only — it does
   not persist agent state, stop the process, and rehydrate in a fresh process.
   (Workflow ``Context`` can be ``ctx.to_dict()``/``Context.from_dict()``
   serialized for checkpointing, but the refund HITL contract here is a clean
   two-process suspend/resume, which LlamaIndex has no turnkey API for.) We
   hand-roll it: phase 1 persists state to a ``.state`` file and returns; phase 2
   (a separate process) loads it and finishes.

4. router — hand-rolled keyword classifier mapping the human's free-text answer
   to approve/reject/escalate, with word-boundary matching. (Colmena: a
   ``router`` node.)

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
Token accounting is via proxy spans, so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.tools import FunctionTool

from bench_common import RunnerArgs, extract_answer_dict, scenario_refund

_MAX_RETRIES = 3
_APPROVE_WORDS = ("approve", "yes", "ok", "okay", "go ahead", "confirm", "agree")
_REJECT_WORDS = ("reject", "deny", "no", "decline", "refuse")
_ESCALATE_WORDS = ("escalate", "manager", "supervisor", "review", "higher")


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


def _draft_with_critic(llm: Any, base_prompt: str) -> tuple[dict[str, Any], int]:
    """LLM drafts a refund decision; rule-check it and re-prompt on violation.

    Returns (decision_dict, retries). ``retries`` counts re-prompts after the
    first draft (0 means the first draft was already compliant). Plain LlamaIndex
    ``llm.chat`` over ``ChatMessage`` turns — no native critic loop.
    """
    instruction = (
        f"{base_prompt}\n\nCustomer: {scenario_refund.CUSTOMER_MESSAGE}\n"
        f"Requested amount: {scenario_refund.REQUEST['amount']} USD\n"
        f"Policy: {scenario_refund.POLICY_TEXT}\n\n"
        'Respond with ONLY a JSON object: '
        '{"decision": "approve|partial|reject|escalate", "amount": <number>, '
        '"justification": "<text>"}.'
    )
    feedback = ""
    decision: dict[str, Any] = {}
    for attempt in range(_MAX_RETRIES + 1):
        prompt = instruction + (f"\n\nYour previous draft was rejected: {feedback}\n"
                                "Fix it and respect the policy." if feedback else "")
        raw = llm.chat([ChatMessage(role=MessageRole.USER, content=prompt)])
        decision = extract_answer_dict(str(raw.message.content))
        if not scenario_refund.policy_violation(decision):
            return decision, attempt
        feedback = (
            f"You chose decision={decision.get('decision')} amount={decision.get('amount')}, "
            "but a refund above 100 USD must be 'partial' (<=100) or 'escalate' — "
            "never a full 'approve' over 100."
        )
    return decision, _MAX_RETRIES


def _confirm_with_masked_tool(llm: Any, decision: dict[str, Any]) -> str:
    """Confirm the decision via a FunctionAgent that calls a payment tool whose
    result is SCRUBBED of the secret before it re-enters the LLM context.

    The ``payment_lookup`` result carries the secret in ``auth_token``. LlamaIndex
    feeds a ``FunctionTool`` return value straight back into the LLM (and the proxy
    sees it on the next turn), so we scrub the secret substring HERE, inside the
    wrapper, before returning it. The masking audit
    (proxy/spans/mask-<run_id>.json) verifies the secret never reached the proxy.
    """

    def run_payment(order_id: str) -> str:
        """Look up an order in the payment gateway. Returns order status info."""
        result = scenario_refund.payment_lookup(order_id, scenario_refund.SECRET)
        # DIY outbound masking: drop the secret field, and defensively scrub the
        # secret substring from anything that remains, before it leaves the tool.
        result.pop("auth_token", None)
        return json.dumps(result).replace(scenario_refund.SECRET, "[REDACTED]")

    payment_tool = FunctionTool.from_defaults(
        fn=run_payment,
        name="run_payment",
        description="Look up an order in the payment gateway. Returns order status info.",
    )
    agent = FunctionAgent(
        tools=[payment_tool],
        llm=llm,
        system_prompt="You are a payments agent that never exposes credentials.",
        verbose=False,
        timeout=None,
    )
    prompt = (
        f"Look up order {scenario_refund.REQUEST['order_id']} with the run_payment "
        f"tool, then write ONE line confirming this refund decision: "
        f"{json.dumps(decision)}. Do not reveal any credentials."
    )

    async def _run() -> str:
        result = await agent.run(user_msg=prompt, max_iterations=10)
        if hasattr(result, "response"):
            return result.response.content or ""
        return str(result)

    return asyncio.run(_run())


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
    decision, retries = _draft_with_critic(llm, task_def["prompt"])
    # The confirm call MUST go through the proxy with the scrubbed tool result so
    # the masking audit is meaningful (it scans this call's messages for the secret).
    _confirm_with_masked_tool(llm, decision)

    _state_path(args).write_text(
        json.dumps({"answer": decision, "retries": retries}, indent=2)
    )
    return {"decision": None}, _zero_usage(), {"suspended": True}
