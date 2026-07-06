"""Task 6 — OpenAI Agents SDK production refund agent (the "hardened" competitor arm).

Hand-rolls the four Demo #6 capabilities (Colmena expresses them as declarative
config):
  1. control flow — imperative draft -> critic-retry -> confirm -> HITL.
  2. durable HITL — DIY two-phase: PHASE 1 drafts + confirms, persists the decision to
     a ``<output>.state`` JSON file, exits; PHASE 2 (fresh process) loads it + applies
     the human answer. The SDK has no native durable checkpointer, so the state file IS
     the hand-rolled durability.
  3. critic-retry — a Python loop that re-drafts while ``policy_violation`` holds.
  4. outbound masking — the ``run_payment`` tool drops ``auth_token`` and scrubs the
     secret substring before its result re-enters context.

Reasoning disabled (see task08) to avoid the Gemini empty-completion on tool prompts.
Mirrors the LangGraph/Pydantic-AI arms.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agents import Agent, ModelSettings, Runner, function_tool

from bench_common import RunnerArgs, extract_answer_dict, scenario_refund

_MAX_RETRIES = 3
_SETTINGS = ModelSettings(temperature=0.0, extra_body={"reasoning_effort": "disable"})

_APPROVE_WORDS = ("approve", "yes", "ok", "okay", "go ahead", "confirm", "agree")
_REJECT_WORDS = ("reject", "deny", "no", "decline", "refuse")
_ESCALATE_WORDS = ("escalate", "manager", "supervisor", "review", "higher")


def classify_intent(answer: str) -> str:
    """Map a human's free-text answer to approve/reject/escalate (identical to the
    other runners so every framework classifies the same way)."""
    text = (answer or "").lower()

    def has(words: tuple[str, ...]) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)

    if has(_ESCALATE_WORDS):
        return "escalate"
    if has(_REJECT_WORDS):
        return "reject"
    if has(_APPROVE_WORDS):
        return "approve"
    return "escalate"


def _state_path(args: RunnerArgs) -> Path:
    return Path(str(args.output) + ".state")


def _zero() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}


def _best_effort(agent: Agent, prompt: str) -> str:
    for _ in range(3):
        try:
            return str(Runner.run_sync(agent, prompt).final_output or "")
        except Exception:  # noqa: BLE001
            pass
    return ""


def run(
    task_def: dict[str, Any], model: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    # ---- PHASE 2: resume from the persisted state ---------------------------
    if args.resume_state is not None:
        state = json.loads(Path(args.resume_state).read_text())
        decision = state.get("decision", {})
        retries = int(state.get("retries", 0))
        human_answer = args.resume_answer or scenario_refund.CANONICAL_HUMAN_ANSWER
        return decision, _zero(), {"final_intent": classify_intent(human_answer), "retries": retries}

    # ---- PHASE 1: draft (+critic-retry) + masked confirm, then suspend -------
    base_prompt = task_def["prompt"]
    draft_agent = Agent(
        name="RefundDrafter",
        instructions="You are a careful refund-decision agent. Follow the policy exactly.",
        model=model, model_settings=_SETTINGS,
    )

    decision: dict[str, Any] = {}
    retries = 0
    feedback = ""
    for _ in range(_MAX_RETRIES + 1):
        instruction = (
            f"{base_prompt}\n\nCustomer: {scenario_refund.CUSTOMER_MESSAGE}\n"
            f"Requested amount: {scenario_refund.REQUEST['amount']} USD\n"
            f"Policy: {scenario_refund.POLICY_TEXT}\n\n"
            'Respond with ONLY a JSON object: {"decision": "approve|partial|reject|escalate", '
            '"amount": <number>, "justification": "<text>"}.'
        )
        prompt = instruction + (
            f"\n\nYour previous draft was rejected: {feedback}\nFix it and respect the policy."
            if feedback else ""
        )
        decision = extract_answer_dict(_best_effort(draft_agent, prompt))
        if not scenario_refund.policy_violation(decision):
            break
        feedback = (
            f"You chose decision={decision.get('decision')} amount={decision.get('amount')}, "
            "but a refund above 100 USD must be 'partial' (<=100) or 'escalate' — "
            "never a full 'approve' over 100."
        )
        retries += 1

    @function_tool
    def run_payment(order_id: str) -> str:
        """Look up an order in the payment gateway. Returns order status info."""
        result = scenario_refund.payment_lookup(order_id, scenario_refund.SECRET)
        result.pop("auth_token", None)  # DIY outbound masking
        return json.dumps(result).replace(scenario_refund.SECRET, "[REDACTED]")

    confirm_agent = Agent(
        name="RefundConfirmer",
        instructions="Confirm the refund decision in one line. Never reveal any credentials.",
        tools=[run_payment], model=model, model_settings=_SETTINGS,
    )
    _best_effort(
        confirm_agent,
        f"Look up order {scenario_refund.REQUEST['order_id']} with the run_payment tool, "
        f"then write ONE line confirming this refund decision: {json.dumps(decision)}. "
        "Do not reveal any credentials.",
    )

    _state_path(args).write_text(json.dumps({"decision": decision, "retries": retries}, indent=2))
    return {"decision": None}, _zero(), {"suspended": True}
