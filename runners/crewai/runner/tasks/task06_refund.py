"""Task 6 — CrewAI refund agent (Demo #4): hand-rolled HITL + critic + masking.

This is the IMPERATIVE counterpart to Colmena's declarative refund DAG. Every
production capability Colmena expresses as a node + config flag is hand-coded
here, and the extra Python is the node-vs-code cost we measure.

What CrewAI gives us natively vs. what we hand-roll:

1. draft + critic-retry  — hand-rolled. CrewAI Tasks have `guardrail`/`max_retries`
   but the retry is opaque (no feedback injection / count we can score, and it
   re-runs the whole agent). We drive an explicit loop with `crewai.LLM.call`,
   rule-check via `scenario_refund.policy_violation`, and re-prompt with feedback.

2. confirm w/ masked payment tool — tool-calling is native (Agent + `@tool` + Crew,
   mirrors task04_expert), but CrewAI has NO outbound tool-result masking. The
   tool returns the secret `auth_token`; we hand-wrap the tool to SCRUB the secret
   substring out of the result BEFORE it is returned to the framework (and thus
   before it reaches the LLM context / the proxy). This DIY scrub is the masking
   cost. Colmena does it with `secure: true` on the node (zero user code).

3. HITL approval (durable, cross-process) — hand-rolled. CrewAI's only native HITL
   is `Task(human_input=True)`, which performs a BLOCKING, in-process
   `input()`-style console prompt during `kickoff()` and resumes in the SAME
   process (see https://docs.crewai.com/en/concepts/tasks#task-attributes,
   `human_input: Optional[bool]` — "Whether the task should have a human review
   the final answer"). There is NO native API to persist agent state, stop the
   process, and rehydrate in a fresh process. FINDING: CrewAI has no durable /
   cross-process suspend primitive. We hand-roll it: phase 1 persists state to a
   `.state` file and returns; phase 2 (a separate process) loads it and finishes.

4. router — hand-rolled keyword/LLM classifier mapping the human's free-text answer
   to approve/reject/escalate. (Colmena: a `router` node.)

Handler contract: `run(task_def, llm, args) -> (answer, usage, extras)`.
Token accounting is via proxy spans, so `usage` is all zeros by contract.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, Task
from crewai.tools import tool

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

    Returns (decision_dict, retries). `retries` counts re-prompts after the
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
        raw = llm.call([{"role": "user", "content": prompt}])
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
    """Confirm the decision via an LLM that calls a payment tool whose result is
    SCRUBBED of the secret before it re-enters the LLM context.

    The `payment_lookup` result carries the secret in `auth_token`. CrewAI feeds a
    tool's return string straight back into the LLM (and the proxy sees it), so we
    scrub the secret substring HERE, inside the wrapper, before returning it. The
    masking audit (proxy/spans/mask-<run_id>.json) verifies the secret never
    reached the proxy.
    """

    @tool("run_payment")
    def run_payment(order_id: str) -> str:
        """Look up an order in the payment gateway. Returns order status info."""
        result = scenario_refund.payment_lookup(order_id, scenario_refund.SECRET)
        # DIY outbound masking: drop the secret field, and defensively scrub the
        # secret substring from anything that remains, before it leaves the tool.
        result.pop("auth_token", None)
        safe = json.dumps(result).replace(scenario_refund.SECRET, "[REDACTED]")
        return safe

    agent = Agent(
        role="refund confirmer",
        goal="Confirm a refund decision after verifying the order via the payment tool.",
        backstory="A payments agent that never exposes credentials.",
        llm=llm, tools=[run_payment], allow_delegation=False, verbose=False,
    )
    crew_task = Task(
        description=(
            f"Look up order {scenario_refund.REQUEST['order_id']} with the run_payment "
            f"tool, then write ONE line confirming this refund decision: "
            f"{json.dumps(decision)}. Do not reveal any credentials."
        ),
        expected_output="A one-line confirmation.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)
    return str(crew.kickoff())


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
    _confirm_with_masked_tool(llm, decision, args.run_id)

    _state_path(args).write_text(
        json.dumps({"answer": decision, "retries": retries}, indent=2)
    )
    return {"decision": None}, _zero_usage(), {"suspended": True}
