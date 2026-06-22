"""Task 6 — Colmena refund agent (Demo #4): thin TWO-PHASE runner.

The agent is a DECLARATIVE DAG (``runners/colmena/runner/dags/refund_agent.json``):
``trigger -> draft(llm) -> validate(rule-based policy, cyclic retry) ->
get_key(secure_suspend) -> pay(python, secure) -> review(suspend HITL) ->
decide(router) -> log``. This module is a THIN runner that only drives the
two-phase HITL protocol via ``colmena.run_dag`` — all the agent logic lives in
the JSON.

Two suspends fire in sequence:
  1. ``get_key`` (secure_suspend) provisions the payment key ``pay_key``.
  2. ``review`` (suspend) asks the human to approve the refund.

So phase 2 resumes TWICE: first with ``A[pay_key]: <SECRET>`` (the payment key),
then — if the run suspends again at the approval gate — with
``A[approve_refund]: <human answer>``.

Masking: the ``pay`` python node carries config ``secure: true`` and returns the
secret ONLY in its own ``auth_token`` field (whole-field hashing), so only that
field is masked to the LLM/router while ``order_info`` stays readable.

Phase 1 (``args.resume_state is None``): run to the first suspend (secure_suspend),
persist a ``.state`` file next to ``args.output`` with ``{session, resume_id,
prompt}``, return a null-decision answer with ``extras.suspended = True``.

Phase 2 (``args.resume_state`` set): load the state, resume the secure_suspend
with the secret, then the approval suspend, then extract the final draft decision
JSON from the graph output.

Engine env mirrors task04_expert's ``_ensure_env`` (proxy key, Postgres URL for
the llm_call/router ``connection_url``, durable storage, SECURE_VALUES_KEY).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bench_common import RunnerArgs
from bench_common import scenario_refund

_DAG_PATH = Path(__file__).resolve().parents[1] / "dags" / "refund_agent.json"


def _ensure_env(caller: Any) -> None:
    """Env the engine needs at run_dag time: proxy key, Postgres URL, durable
    storage, secure-values key (mirrors task04_expert)."""
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    if not os.environ.get("SECURE_VALUES_KEY"):
        os.environ["SECURE_VALUES_KEY"] = "0" * 64
    if not os.environ.get("COLMENA_LOCAL_STORAGE_DIR"):
        storage_dir = Path("/tmp") / "colmena-bench-storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        os.environ["COLMENA_LOCAL_STORAGE_DIR"] = str(storage_dir)
        os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")


def _load_dag() -> dict[str, Any]:
    return json.loads(_DAG_PATH.read_text())


def _zero_usage() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}


def _is_suspended(out: dict[str, Any]) -> bool:
    return out.get("__colmena_status") == "SUSPENDED"


def _pending_question_ids(out: dict[str, Any]) -> list[str]:
    """The ``id``s the engine is currently asking for at this suspend.

    The suspended payload carries ``questions: [{"id": ..., "question": ...}]``.
    Resuming must answer with ``A[<id>]: ...`` matching one of these ids, or the
    engine rejects it (``A[<id>] is not in the expected id set``). The two
    suspends in this DAG ask for ``pay_key`` (secure_suspend) then
    ``approve_refund`` (HITL) — but the confirm agent may skip the get_key tool
    call (LLM non-determinism), so we must read the live id rather than assume the
    order."""
    qs = out.get("questions")
    ids: list[str] = []
    if isinstance(qs, list):
        for q in qs:
            if isinstance(q, dict) and isinstance(q.get("id"), str):
                ids.append(q["id"])
    return ids


def _state_path(args: RunnerArgs) -> Path:
    return Path(str(args.output) + ".state")


def _build_prompt(task_def: dict[str, Any]) -> str:
    return (
        f"{task_def['prompt']}\n\n"
        f"Customer: {scenario_refund.CUSTOMER_MESSAGE}\n"
        f"Amount: {scenario_refund.REQUEST['amount']}"
    )


def _extract_decision(final: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the validated draft decision JSON out of the final graph output.

    The ``validate`` node, on the FINISHED (non-violating) branch, emits
    ``approved`` (the parsed dict) and ``decision_json`` (its JSON string).
    Search the validate node output first, then fall back to scanning any node
    output that looks like a refund decision.
    """
    val = final.get("validate")
    if isinstance(val, dict):
        approved = val.get("approved")
        if isinstance(approved, dict) and "decision" in approved:
            return approved
        dj = val.get("decision_json")
        if isinstance(dj, str):
            try:
                parsed = json.loads(dj)
                if isinstance(parsed, dict) and "decision" in parsed:
                    return parsed
            except Exception:  # noqa: BLE001
                pass
    # Fallback: scan every node output for a dict carrying a `decision` key.
    for node_out in final.values():
        if isinstance(node_out, dict):
            for v in node_out.values():
                if isinstance(v, dict) and "decision" in v and "amount" in v:
                    return v
    return None


def run(
    task_def: dict[str, Any], caller: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    import colmena

    _ensure_env(caller)
    dag = _load_dag()
    session_id = f"refund_{args.run_id}"

    # ---- Phase 1: run to the first suspend (secure_suspend / get_key) --------
    if args.resume_state is None:
        prompt = _build_prompt(task_def)
        result_json = colmena.run_dag(
            dag, None, None, {"prompt": prompt}, True, session_id
        )
        out = json.loads(result_json)
        if not _is_suspended(out):
            # Did not suspend — surface the raw output so the failure is visible.
            return (
                {"decision": None},
                _zero_usage(),
                {"suspended": False, "final": out, "error": "phase 1 did not suspend"},
            )
        state = {
            "session": session_id,
            "resume_id": out.get("session_id"),
            "prompt": prompt,
            # The id(s) THIS suspend is asking for, so phase 2 answers the right
            # one first (the confirm agent may skip get_key, suspending straight
            # at the human-approval gate).
            "pending_ids": _pending_question_ids(out),
        }
        _state_path(args).write_text(json.dumps(state, indent=2))
        return ({"decision": None}, _zero_usage(), {"suspended": True})

    # ---- Phase 2: resume each suspend in turn, keyed by the LIVE question id --
    # The DAG suspends (up to) twice: secure_suspend(`pay_key`) then HITL
    # (`approve_refund`). The confirm agent may skip the get_key tool call, so we
    # don't assume the order — we read the pending question id from each suspend
    # payload and answer the one the engine is actually asking for.
    state = json.loads(Path(args.resume_state).read_text())
    session_id = state["session"]
    resume_id = state["resume_id"]

    human_answer = args.resume_answer or scenario_refund.CANONICAL_HUMAN_ANSWER
    if not human_answer.startswith("A[approve_refund]:"):
        human_answer = f"A[approve_refund]: {human_answer}"

    def _answer_for(qid: str) -> str:
        if qid == "pay_key":
            return f"A[pay_key]: {scenario_refund.SECRET}"
        return human_answer

    # First answer is driven by the id phase 1 recorded as pending (defaults to
    # pay_key for back-compat with older state files that didn't persist it).
    pending_ids = state.get("pending_ids") or ["pay_key"]
    next_answer = _answer_for(pending_ids[0])

    out: dict[str, Any] = {}
    for _ in range(4):  # at most two suspends to clear; cap defensively
        result_json = colmena.run_dag(
            dag, resume_id, next_answer, None, True, session_id
        )
        out = json.loads(result_json)
        if not _is_suspended(out):
            break
        ids = _pending_question_ids(out)
        resume_id = out.get("session_id", resume_id)
        # Answer the pending id; default to the human answer for the HITL gate.
        next_answer = _answer_for(ids[0]) if ids else human_answer

    decision = _extract_decision(out)
    answer = decision if decision is not None else {"decision": None}
    extras: dict[str, Any] = {"final": out}
    # The router branch that fired (approve/reject/escalate), if observable.
    decide = out.get("decide")
    if isinstance(decide, dict):
        sel = decide.get("__decision", {})
        if isinstance(sel, dict) and sel.get("selected_branch"):
            extras["router_branch"] = sel["selected_branch"]
    return answer, _zero_usage(), extras
