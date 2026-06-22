"""Task 6 — LangGraph refund agent (Demo #4): NATIVE graph + durable HITL.

This is the HONEST counterpart to the three code-first frameworks. LangGraph is a
GRAPH framework with a native durable human-in-the-loop primitive, so wherever it
ships a real primitive we USE it (and mark it "native"); where it does not, we
hand-roll it (and mark it "DIY"). Per-feature assessment for LangGraph:

1. graph                — NATIVE. The whole agent is a ``StateGraph`` of nodes
   (draft → confirm → hitl → router) wired with edges, compiled with a
   checkpointer.  No imperative driver loop.

2. critic_retry         — NATIVE. The draft node rule-checks its own output
   (``scenario_refund.policy_violation``) and a CONDITIONAL EDGE loops back to
   ``draft`` with feedback in the graph state until compliant or max retries.
   The retry is expressed as a graph cycle, not a Python ``for`` loop.

3. hitl_durable         — NATIVE. The ``hitl`` node calls LangGraph's
   ``interrupt()`` over a PERSISTENT ``SqliteSaver`` checkpointer backed by a
   FILE.  Phase 1 (one process) runs to the interrupt and the checkpoint is
   flushed to disk; phase 2 (a FRESH process) re-opens the same sqlite file +
   ``thread_id`` and resumes with ``Command(resume=<human answer>)``.  This
   genuinely survives a process restart — matching Colmena's durable suspend.

4. masking              — DIY. LangGraph has NO native OUTBOUND tool-result
   masking.  The ``payment_lookup`` result carries the secret in ``auth_token``;
   we hand-scrub the field + secret substring inside the tool wrapper BEFORE it
   re-enters the LLM context / reaches the proxy.  (Colmena: ``secure: true``,
   zero user code.)

Handler contract: ``run(task_def, llm, args) -> (answer, usage, extras)``.
Token accounting is via proxy spans, so ``usage`` is all zeros by contract.

Two-phase contract (matches the driver):
- Phase 1 (``args.resume_state is None``): draft(+critic) + confirm-with-masked-
  tool, reach the HITL ``interrupt()``, persist a tiny ``.state`` file holding the
  ``thread_id`` + checkpointer DB path (the heavy state lives in the checkpointer).
  Return ``({"decision": None}, zero_usage, {"suspended": True})``.
- Phase 2 (``args.resume_state`` set): reconnect the SAME SqliteSaver with the
  saved thread_id, resume via ``Command(resume=human_answer)``, classify intent,
  return ``(decision, zero_usage, {"final_intent": intent, "retries": retries})``.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from bench_common import RunnerArgs, extract_answer_dict, scenario_refund

_MAX_RETRIES = 3
_MAX_TOOL_ITERS = 6
_APPROVE_WORDS = ("approve", "yes", "ok", "okay", "go ahead", "confirm", "agree")
_REJECT_WORDS = ("reject", "deny", "no", "decline", "refuse")
_ESCALATE_WORDS = ("escalate", "manager", "supervisor", "review", "higher")

# Module-level handle so graph nodes (which take only `state`) can reach the LLM.
_LLM: Any = None


def _state_path(args: RunnerArgs) -> Path:
    return Path(str(args.output) + ".state")


def _ckpt_path(args: RunnerArgs) -> Path:
    """File-backed checkpointer DB. Lives next to the output so phase 2 (a fresh
    process) can reconnect to the SAME sqlite file the interrupt was flushed to."""
    return Path(str(args.output) + ".ckpt.sqlite")


def _zero_usage() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}


def classify_intent(answer: str) -> str:
    """Map a human's free-text approval answer to approve/reject/escalate.

    Pure + deterministic so it is unit-testable. Escalate and reject are checked
    before approve because phrases like "escalate, do not approve" contain
    approve-ish tokens. Matching is on word boundaries so "no" does not fire
    inside "not sure"."""
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


# --------------------------------------------------------------------------- #
# Graph state                                                                  #
# --------------------------------------------------------------------------- #
class RefundState(TypedDict, total=False):
    _base_prompt: str
    decision: dict[str, Any]
    retries: int
    feedback: str
    human_answer: str
    intent: str


# --------------------------------------------------------------------------- #
# Masked payment tool (DIY outbound scrub)                                     #
# --------------------------------------------------------------------------- #
@tool("run_payment")
def run_payment(order_id: str) -> str:
    """Look up an order in the payment gateway. Returns order status info."""
    result = scenario_refund.payment_lookup(order_id, scenario_refund.SECRET)
    # DIY outbound masking: drop the secret field, then defensively scrub the
    # secret substring from anything that remains, BEFORE it leaves the tool and
    # re-enters the LLM context / reaches the proxy.
    result.pop("auth_token", None)
    return json.dumps(result).replace(scenario_refund.SECRET, "[REDACTED]")


# --------------------------------------------------------------------------- #
# Graph nodes                                                                  #
# --------------------------------------------------------------------------- #
def _draft_node(state: RefundState) -> dict[str, Any]:
    """LLM drafts a refund decision. The conditional edge after this node
    rule-checks the decision and loops BACK here (with feedback) on violation —
    the critic-retry is the graph cycle, not a Python loop."""
    base_prompt = state.get("_base_prompt", "")  # injected via partial state
    instruction = (
        f"{base_prompt}\n\nCustomer: {scenario_refund.CUSTOMER_MESSAGE}\n"
        f"Requested amount: {scenario_refund.REQUEST['amount']} USD\n"
        f"Policy: {scenario_refund.POLICY_TEXT}\n\n"
        'Respond with ONLY a JSON object: '
        '{"decision": "approve|partial|reject|escalate", "amount": <number>, '
        '"justification": "<text>"}.'
    )
    feedback = state.get("feedback", "")
    prompt = instruction + (
        f"\n\nYour previous draft was rejected: {feedback}\n"
        "Fix it and respect the policy." if feedback else ""
    )
    raw = _LLM.invoke([HumanMessage(content=prompt)])
    decision = extract_answer_dict(str(raw.content))
    return {"decision": decision}


def _critic_edge(state: RefundState) -> str:
    """Conditional edge: gate the draft. Loop back to ``draft`` (incrementing the
    retry count + recording feedback in state) on a policy violation, until
    compliant or the retry budget is exhausted. Returns the next node name."""
    decision = state.get("decision", {})
    retries = state.get("retries", 0)
    if not scenario_refund.policy_violation(decision) or retries >= _MAX_RETRIES:
        return "confirm"
    return "retry"


def _retry_node(state: RefundState) -> dict[str, Any]:
    """Record critic feedback + bump the retry counter, then the static edge
    sends us back to ``draft``. (Separate node so the counter mutation lives in
    the graph state, not a closure.)"""
    decision = state.get("decision", {})
    feedback = (
        f"You chose decision={decision.get('decision')} amount={decision.get('amount')}, "
        "but a refund above 100 USD must be 'partial' (<=100) or 'escalate' — "
        "never a full 'approve' over 100."
    )
    return {"feedback": feedback, "retries": state.get("retries", 0) + 1}


def _confirm_node(state: RefundState) -> dict[str, Any]:
    """Confirm the decision via an LLM that calls the masked payment tool. The
    tool result is SCRUBBED of the secret inside the wrapper before it re-enters
    the LLM context, so the masking audit (which scans this proxy call) is
    meaningful. State is unchanged; the value here is the audited proxy traffic."""
    llm_with_tools = _LLM.bind_tools([run_payment])
    decision = state.get("decision", {})
    prompt = (
        f"Look up order {scenario_refund.REQUEST['order_id']} with the run_payment "
        f"tool, then write ONE line confirming this refund decision: "
        f"{json.dumps(decision)}. Do not reveal any credentials."
    )
    messages: list[Any] = [HumanMessage(content=prompt)]
    for _ in range(_MAX_TOOL_ITERS):
        ai_msg: AIMessage = llm_with_tools.invoke(messages)
        messages.append(ai_msg)
        tool_calls = ai_msg.tool_calls or []
        if not tool_calls:
            break
        for tc in tool_calls:
            order_id = tc["args"].get("order_id", scenario_refund.REQUEST["order_id"])
            try:
                result = run_payment.invoke(order_id)
            except Exception as e:  # noqa: BLE001 — surface to the agent
                result = f"ERROR: {type(e).__name__}: {e}"
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return {}


def _hitl_node(state: RefundState) -> dict[str, Any]:
    """NATIVE durable HITL: ``interrupt()`` suspends the graph and the checkpointer
    flushes the full state to disk. Phase 2 resumes with ``Command(resume=...)``;
    the value passed to resume becomes the return value of ``interrupt()`` here."""
    human_answer = interrupt(
        {
            "question": "A human must approve/reject/escalate this refund.",
            "decision": state.get("decision", {}),
        }
    )
    return {"human_answer": human_answer}


def _router_node(state: RefundState) -> dict[str, Any]:
    """Branch on the human's free-text answer (approve/reject/escalate)."""
    return {"intent": classify_intent(state.get("human_answer", ""))}


def _build_graph(checkpointer: Any):
    g = StateGraph(RefundState)
    g.add_node("draft", _draft_node)
    g.add_node("retry", _retry_node)
    g.add_node("confirm", _confirm_node)
    g.add_node("hitl", _hitl_node)
    g.add_node("router", _router_node)

    g.add_edge(START, "draft")
    # critic-retry as a graph cycle: draft -> (retry -> draft | confirm)
    g.add_conditional_edges("draft", _critic_edge, {"retry": "retry", "confirm": "confirm"})
    g.add_edge("retry", "draft")
    g.add_edge("confirm", "hitl")
    g.add_edge("hitl", "router")
    g.add_edge("router", END)
    return g.compile(checkpointer=checkpointer)


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    global _LLM
    _LLM = llm

    # ---- Phase 2: reconnect the persistent checkpointer and resume ----------
    if args.resume_state is not None:
        state_meta = json.loads(Path(args.resume_state).read_text())
        thread_id = state_meta["thread_id"]
        db_path = state_meta["ckpt_path"]
        human_answer = args.resume_answer or scenario_refund.CANONICAL_HUMAN_ANSWER

        # NATIVE: a FRESH process re-opens the SAME sqlite checkpointer file and
        # resumes the interrupted graph from disk. check_same_thread=False so the
        # connection is usable regardless of the calling thread.
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            checkpointer = SqliteSaver(conn)
            graph = _build_graph(checkpointer)
            config = {"configurable": {"thread_id": thread_id}}
            result = graph.invoke(Command(resume=human_answer), config=config)
        finally:
            conn.close()

        decision = result.get("decision", {})
        intent = result.get("intent", classify_intent(human_answer))
        return (
            decision,
            _zero_usage(),
            {"final_intent": intent, "retries": result.get("retries", 0)},
        )

    # ---- Phase 1: run draft(+critic) + confirm, reach the interrupt ---------
    ckpt_path = _ckpt_path(args)
    ckpt_path.unlink(missing_ok=True)  # clean slate for a deterministic smoke
    thread_id = f"demo06_{args.run_id}"

    conn = sqlite3.connect(str(ckpt_path), check_same_thread=False)
    try:
        checkpointer = SqliteSaver(conn)
        graph = _build_graph(checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        # Seed the base prompt into state for the draft node. Invoking runs the
        # graph until the hitl node's interrupt(), which flushes the checkpoint
        # to disk and returns control here (the graph is suspended, not done).
        graph.invoke(
            {"_base_prompt": task_def["prompt"], "retries": 0, "feedback": ""},
            config=config,
        )
    finally:
        conn.close()

    # Persist only the pointers; the heavy state lives in the checkpointer file.
    _state_path(args).write_text(
        json.dumps(
            {"thread_id": thread_id, "ckpt_path": str(ckpt_path)}, indent=2
        )
    )
    return {"decision": None}, _zero_usage(), {"suspended": True}
