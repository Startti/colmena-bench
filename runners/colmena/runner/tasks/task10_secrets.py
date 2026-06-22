"""Task 10 — Colmena secrets agent (Demo #10): thin TWO-PHASE runner.

The agent is a DECLARATIVE DAG (``runners/colmena/runner/dags/secrets_agent.json``):
``trigger -> assistant(llm_call) -> log``. The assistant collects 3 credentials
via the ``get_secrets`` tool (node_type ``secure_suspend``, 3-secret batch) which
returns opaque ``<sv_...>`` handles; it then calls ``connect`` (a ``secure:true``
``python_script`` tool) passing the 3 handles. ``inject_secrets`` decrypts the
handles to the REAL values ONLY inside the connect tool's execution, which POSTs
them (urllib) to ``BENCH_MOCK_URL`` (read from env at run time). The LLM/proxy
never see the real secret. This module is a THIN runner that only drives the
two-phase suspend/resume protocol via ``colmena.run_dag`` — all the agent logic
lives in the JSON.

A SINGLE suspend fires: the ``get_secrets`` (secure_suspend) batch that asks for
all 3 credential ids at once. So phase 2 resumes (typically once) answering each
pending id with its real value from ``scenario_secrets.secrets()``.

Masking: the ``connect`` python node carries config ``secure: true``; the engine
decrypts the handles only to run the python tool, then DagToolExecutor re-masks
the tool result before it re-enters the LLM conversation.

Phase 1 (``args.resume_state is None``): run to the first suspend (secure_suspend),
persist a ``.state`` file next to ``args.output`` with ``{session, resume_id,
prompt, pending_ids}``, return ``{"connected": None}`` with
``extras.suspended = True``.

Phase 2 (``args.resume_state`` set): load the state, resume the secure_suspend
answering each pending id with its real value, and report delivery.

Engine env mirrors task06_refund's ``_ensure_env`` (proxy key, Postgres URL for
the llm_call ``connection_url``, durable storage, SECURE_VALUES_KEY). It does NOT
set ``BENCH_MOCK_URL`` — the DRIVER sets that in the subprocess env before
invoking, and the connect tool reads ``os.environ['BENCH_MOCK_URL']`` in-process.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bench_common import RunnerArgs
from bench_common import scenario_secrets as ss

_DAG_PATH = Path(__file__).resolve().parents[1] / "dags" / "secrets_agent.json"


def _ensure_env(caller: Any) -> None:
    """Env the engine needs at run_dag time: proxy key, Postgres URL, durable
    storage, secure-values key (mirrors task06_refund). Does NOT touch
    BENCH_MOCK_URL — the driver sets that in the subprocess env."""
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


def _load_dag(caller: Any) -> dict[str, Any]:
    dag = json.loads(_DAG_PATH.read_text())
    # The DAG carries ${MODEL_ALIAS} for the model; substitute the live alias.
    dag["nodes"]["assistant"]["config"]["model"] = caller.model_alias
    return dag


def _zero_usage() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}


def _is_suspended(out: dict[str, Any]) -> bool:
    return out.get("__colmena_status") == "SUSPENDED"


def _pending_question_ids(out: dict[str, Any]) -> list[str]:
    """The ``id``s the engine is currently asking for at this suspend.

    The suspended payload carries ``questions: [{"id": ..., "question": ...}]``.
    Resuming must answer with ``A[<id>]: ...`` matching one of these ids, or the
    engine rejects it (``A[<id>] is not in the expected id set``). The single
    secure_suspend in this DAG asks for all 3 credential ids at once."""
    qs = out.get("questions")
    ids: list[str] = []
    if isinstance(qs, list):
        for q in qs:
            if isinstance(q, dict) and isinstance(q.get("id"), str):
                ids.append(q["id"])
    return ids


def _state_path(args: RunnerArgs) -> Path:
    return Path(str(args.output) + ".state")


def _answer_for(qid: str) -> str:
    """Answer a pending credential id with its REAL value from the scenario."""
    return f"A[{qid}]: {ss.secrets()[qid]}"


def run(
    task_def: dict[str, Any], caller: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    import colmena

    _ensure_env(caller)
    dag = _load_dag(caller)
    session_id = f"secrets_{args.run_id}"

    # ---- Phase 1: run to the first suspend (secure_suspend / get_secrets) -----
    if args.resume_state is None:
        prompt = ss.ONBOARDING_PROMPT
        result_json = colmena.run_dag(
            dag, None, None, {"prompt": prompt}, True, session_id
        )
        out = json.loads(result_json)
        if not _is_suspended(out):
            # Did not suspend — surface the raw output so the failure is visible.
            return (
                {"connected": None},
                _zero_usage(),
                {"suspended": False, "final": out, "error": "phase 1 did not suspend"},
            )
        state = {
            "session": session_id,
            "resume_id": out.get("session_id"),
            "prompt": prompt,
            # The id(s) THIS suspend is asking for (should be all 3 credentials).
            "pending_ids": _pending_question_ids(out),
        }
        _state_path(args).write_text(json.dumps(state, indent=2))
        return ({"connected": None}, _zero_usage(), {"suspended": True})

    # ---- Phase 2: resume the suspend, answering each pending credential id ----
    # The DAG has a single secure_suspend asking for all 3 credentials at once.
    # We read the pending question id from each suspend payload and answer the one
    # the engine is actually asking for; defensively loop in case the engine
    # surfaces the ids across more than one resume.
    state = json.loads(Path(args.resume_state).read_text())
    session_id = state["session"]
    resume_id = state["resume_id"]

    pending_ids = state.get("pending_ids") or ["api_key"]
    next_answer = "\n".join(_answer_for(q) for q in pending_ids)

    round_trips = 0
    out: dict[str, Any] = {}
    for _ in range(4):  # at most one suspend to clear; cap defensively
        result_json = colmena.run_dag(
            dag, resume_id, next_answer, None, True, session_id
        )
        round_trips += 1
        out = json.loads(result_json)
        if not _is_suspended(out):
            break
        ids = _pending_question_ids(out)
        resume_id = out.get("session_id", resume_id)
        next_answer = "\n".join(_answer_for(q) for q in ids) if ids else next_answer

    answer = {"connected": True}
    extras: dict[str, Any] = {
        "arm": "colmena",
        "received_path": os.environ.get("BENCH_MOCK_RECORD"),
        "round_trips": round_trips,
        "final": out,
    }
    return answer, _zero_usage(), extras
