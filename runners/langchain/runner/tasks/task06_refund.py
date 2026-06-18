"""Task 6 — LangChain refund agent (Demo #4): hand-rolled HITL + critic + masking.

This is the IMPERATIVE, hand-rolled counterpart to Colmena's declarative refund
DAG. Every production capability Colmena expresses as a node + config flag is
hand-coded here, and the extra Python is the node-vs-code cost we measure. It
implements the SAME agent as the CrewAI handler
(runners/crewai/runner/tasks/task06_refund.py), in plain LangChain idiom.

What LangChain gives us natively vs. what we hand-roll:

1. draft + critic-retry  — hand-rolled. Plain LangChain has no built-in critic /
   guarded-retry primitive; we drive an explicit loop with ``llm.invoke`` over
   chat messages, rule-check via ``scenario_refund.policy_violation``, and
   re-prompt with feedback (max 3 retries, counted).

2. confirm w/ masked payment tool — tool-calling is native (``llm.bind_tools`` +
   the manual invoke→ToolMessage→invoke loop, mirroring task04_expert), but
   LangChain has NO native OUTBOUND tool-result masking. The tool returns the
   secret ``auth_token``; we hand-wrap the tool to SCRUB the secret substring out
   of the result BEFORE it is returned (and thus before it re-enters the LLM
   context / reaches the proxy). This DIY scrub is the masking cost. Colmena does
   it with ``secure: true`` on the node (zero user code).

3. HITL approval (durable, cross-process) — hand-rolled. LangChain's
   human-in-the-loop / durable-suspend story is delegated to LangGraph: the
   LangChain docs state agents are "built on top of LangGraph ... [which] allows
   us to take advantage of LangGraph's durable execution, human-in-the-loop
   support, persistence, and more" (https://docs.langchain.com/oss/python/langchain/overview
   — the legacy https://python.langchain.com/docs/ concepts page now 308-redirects
   here). The actual suspend/resume primitive is LangGraph's ``interrupt()`` +
   ``Command(resume=...)`` over a checkpointer (https://docs.langchain.com/oss/python/langgraph/overview).
   FINDING: plain LangChain (chains / direct ``llm`` calls, no LangGraph graph +
   checkpointer) has NO durable, cross-process suspend primitive — there is no
   native API to persist agent state, stop the process, and rehydrate in a fresh
   process. We hand-roll it: phase 1 persists state to a ``.state`` file and
   returns; phase 2 (a separate process) loads it and finishes.

4. router — hand-rolled keyword classifier mapping the human's free-text answer to
   approve/reject/escalate, with word-boundary matching. (Colmena: a ``router``
   node.)

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
Token accounting is via proxy spans, so ``usage`` is all zeros by contract.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from bench_common import RunnerArgs, extract_answer_dict, scenario_refund

_MAX_RETRIES = 3
_MAX_TOOL_ITERS = 6
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
    first draft (0 means the first draft was already compliant).
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
        raw = llm.invoke([HumanMessage(content=prompt)])
        decision = extract_answer_dict(str(raw.content))
        if not scenario_refund.policy_violation(decision):
            return decision, attempt
        feedback = (
            f"You chose decision={decision.get('decision')} amount={decision.get('amount')}, "
            "but a refund above 100 USD must be 'partial' (<=100) or 'escalate' — "
            "never a full 'approve' over 100."
        )
    return decision, _MAX_RETRIES


def _confirm_with_masked_tool(llm: Any, decision: dict[str, Any]) -> str:
    """Confirm the decision via an LLM that calls a payment tool whose result is
    SCRUBBED of the secret before it re-enters the LLM context.

    The ``payment_lookup`` result carries the secret in ``auth_token``. LangChain
    feeds a tool's return value back into the LLM via a ToolMessage (and the proxy
    sees it on the next ``invoke``), so we scrub the secret substring HERE, inside
    the wrapper, before returning it. The masking audit
    (proxy/spans/mask-<run_id>.json) verifies the secret never reached the proxy.
    """

    @tool("run_payment")
    def run_payment(order_id: str) -> str:
        """Look up an order in the payment gateway. Returns order status info."""
        result = scenario_refund.payment_lookup(order_id, scenario_refund.SECRET)
        # DIY outbound masking: drop the secret field, and defensively scrub the
        # secret substring from anything that remains, before it leaves the tool.
        result.pop("auth_token", None)
        return json.dumps(result).replace(scenario_refund.SECRET, "[REDACTED]")

    llm_with_tools = llm.bind_tools([run_payment])
    prompt = (
        f"Look up order {scenario_refund.REQUEST['order_id']} with the run_payment "
        f"tool, then write ONE line confirming this refund decision: "
        f"{json.dumps(decision)}. Do not reveal any credentials."
    )
    messages: list[Any] = [HumanMessage(content=prompt)]
    # Manual tool-calling loop (mirrors task04_expert): invoke → run tool →
    # ToolMessage → invoke again, until the model stops calling tools.
    final_text = ""
    for _ in range(_MAX_TOOL_ITERS):
        ai_msg: AIMessage = llm_with_tools.invoke(messages)
        messages.append(ai_msg)
        tool_calls = ai_msg.tool_calls or []
        if not tool_calls:
            final_text = ai_msg.content or ""
            break
        for tc in tool_calls:
            order_id = tc["args"].get("order_id", scenario_refund.REQUEST["order_id"])
            try:
                result = run_payment.invoke(order_id)
            except Exception as e:  # noqa: BLE001 — surface to the agent
                result = f"ERROR: {type(e).__name__}: {e}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return str(final_text)


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
