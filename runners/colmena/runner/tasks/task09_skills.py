"""Demo #9 — Colmena handler: load_skill over a generated knowledge corpus.

Env:
  BENCH_SKILLS_DIR   — corpus dir (materialized by the driver via scenario_skills)
  BENCH_QUESTION_ID  — which QUESTION_BANK entry to answer this invocation
Token counts are returned as zeros; the driver measures colmena tokens by
span-file delta (same protocol as Demo #7/#8).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from bench_common import RunnerArgs
from bench_common import scenario_skills as sk

_DAG = Path(__file__).resolve().parents[1] / "dags" / "skills_agent.json"


def _ensure_env(caller: Any) -> None:
    """Env the engine needs at run_dag time (mirrors task08_codeexec._ensure_env)."""
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    os.environ.setdefault("SECURE_VALUES_KEY", "0" * 64)
    sd = Path("/tmp/colmena-bench-storage")
    sd.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_DIR", str(sd))
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")
    # skills_path points at a corpus dir OUTSIDE the graph JSON dir; Colmena only
    # accepts skill dirs inside COLMENA_SKILLS_ALLOWED_DIRS. Allow the corpus's
    # PARENT so any m{M}_s{seed} corpus under it is permitted.
    skills_dir = os.environ.get("BENCH_SKILLS_DIR")
    if skills_dir:
        parent = str(Path(skills_dir).resolve().parent)
        existing = os.environ.get("COLMENA_SKILLS_ALLOWED_DIRS", "")
        if parent not in existing.split(":"):
            os.environ["COLMENA_SKILLS_ALLOWED_DIRS"] = (
                f"{existing}:{parent}" if existing else parent
            )


def run(task_def: dict, caller: Any, args: RunnerArgs):
    import colmena

    _ensure_env(caller)
    skills_dir = os.environ["BENCH_SKILLS_DIR"]
    qid = os.environ["BENCH_QUESTION_ID"]
    question = next(q for q in sk.QUESTION_BANK if q.id == qid)

    dag = json.loads(_DAG.read_text())
    dag["nodes"]["assistant"]["config"]["model"] = args.model_alias
    dag["nodes"]["assistant"]["config"]["skills_path"] = str(Path(skills_dir).resolve())
    dag["nodes"]["assistant"]["config"].pop("connection_url", None)

    session_id = f"d9_{args.run_id}_{os.getpid()}_{time.time_ns()}"
    raw = colmena.run_dag(dag, None, None, {"prompt": question.text}, True, session_id)
    out = json.loads(raw) if isinstance(raw, str) else raw

    node = out.get("assistant", {}) if isinstance(out, dict) else {}
    if isinstance(node, dict) and "result" in node:
        answer = node["result"]
    elif isinstance(out, dict) and "result" in out:
        answer = out["result"]
    else:
        answer = raw

    skills_used = node.get("skills_used") if isinstance(node, dict) else None
    extras = {
        "arm": "colmena",
        "question_id": qid,
        "skills_used": skills_used,
        "skills_used_count": len(skills_used) if isinstance(skills_used, list) else 0,
    }
    usage = {"input": 0, "output": 0, "cached": 0}
    return str(answer), usage, extras
