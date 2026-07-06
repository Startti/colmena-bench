"""Task 6 — Pydantic AI production refund agent (the "hardened" competitor arm).

Demo #6 scores four production capabilities. Colmena expresses all four as
declarative config; the competitors HAND-ROLL them. This is the Pydantic AI
hand-rolled version:

  1. control flow — an imperative draft -> critic-retry -> confirm -> HITL pipeline.
  2. durable HITL suspend/resume — DIY two-phase: PHASE 1 runs to the approval point,
     persists the drafted decision to a ``<output>.state`` JSON file, and exits;
     PHASE 2 is a FRESH process that loads the state, applies the human answer, and
     emits the final decision. (Pydantic AI has no native durable graph checkpointer,
     so the state file IS the hand-rolled durability — exactly the point of the demo.)
  3. critic-retry — a Python loop: re-draft while ``policy_violation`` holds, up to
     a retry budget, feeding the critic feedback back into the prompt.
  4. outbound secret masking — the ``run_payment`` tool DROPS the ``auth_token`` and
     scrubs the secret substring from its result BEFORE it re-enters the LLM context,
     so the proxy masking audit (which scans the confirm call) sees no plaintext.

Handler contract: ``run(task_def, model, args) -> (answer, usage, extras)``.
Mirrors runners/langgraph/runner/tasks/task06_refund.py (the near-peer native arm).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from bench_common import RunnerArgs, extract_answer_dict, scenario_refund

_MAX_RETRIES = 3

# gemini-2.5-flash thinking can consume the whole completion on tool/structured
# prompts (empty choices -> pydantic_ai IndexError); disable it. See task08.
_SETTINGS = {"temperature": 0.0, "extra_body": {"reasoning_effort": "disable"}}

_APPROVE_WORDS = ("approve", "yes", "ok", "okay", "go ahead", "confirm", "agree")
_REJECT_WORDS = ("reject", "deny", "no", "decline", "refuse")
_ESCALATE_WORDS = ("escalate", "manager", "supervisor", "review", "higher")


def classify_intent(answer: str) -> str:
    """Map a human's free-text approval answer to approve/reject/escalate.
    Escalate and reject are checked before approve because phrases like
    "escalate, do not approve" contain approve-ish tokens; matching is on word
    boundaries so "no" does not fire inside "not sure". (Copied from the LangGraph
    arm so every framework classifies identically.)"""
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


def _state_path(args: RunnerArgs) -> Path:
    return Path(str(args.output) + ".state")


def _zero() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}


def _best_effort(agent: Agent, prompt: str) -> str:
    for _ in range(3):
        try:
            return str(getattr(agent.run_sync(prompt), "output", "") or "")
        except Exception:  # noqa: BLE001 — transient empty completions
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
        intent = classify_intent(human_answer)
        return decision, _zero(), {"final_intent": intent, "retries": retries}

    # ---- PHASE 1: draft (+critic-retry) + masked confirm, then suspend -------
    base_prompt = task_def["prompt"]
    draft_agent = Agent(
        model,
        system_prompt="You are a careful refund-decision agent. Follow the policy exactly.",
        model_settings=_SETTINGS,
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

    # Confirm via an LLM that calls the MASKED payment tool. The tool scrubs the
    # secret before its result re-enters the context, so the confirm call the proxy
    # audits carries no plaintext credential.
    confirm_agent = Agent(
        model,
        system_prompt="Confirm the refund decision in one line. Never reveal any credentials.",
        model_settings=_SETTINGS,
    )

    @confirm_agent.tool_plain
    def run_payment(order_id: str) -> str:
        """Look up an order in the payment gateway. Returns order status info."""
        result = scenario_refund.payment_lookup(order_id, scenario_refund.SECRET)
        # DIY outbound masking: drop the secret field, then scrub the secret
        # substring from anything that remains, BEFORE it leaves the tool.
        result.pop("auth_token", None)
        return json.dumps(result).replace(scenario_refund.SECRET, "[REDACTED]")

    _best_effort(
        confirm_agent,
        f"Look up order {scenario_refund.REQUEST['order_id']} with the run_payment tool, "
        f"then write ONE line confirming this refund decision: {json.dumps(decision)}. "
        "Do not reveal any credentials.",
    )

    # SUSPEND: persist the decision + retry count; a fresh Phase-2 process resumes.
    _state_path(args).write_text(json.dumps({"decision": decision, "retries": retries}, indent=2))
    return {"decision": None}, _zero(), {"suspended": True}
