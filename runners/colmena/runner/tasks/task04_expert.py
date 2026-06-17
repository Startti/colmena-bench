"""Task 4 expert — Colmena, ``run_sql`` tool over SQLite via ``colmena.run_dag``.

This is the Colmena analogue of the five Python experts (CrewAI/LangChain/…):
the agent answers 20 analytical questions by calling a ``run_sql(query)`` tool
instead of reading the CSV in context. Tokens scale with questions, ~flat across
dataset sizes.

SQL-tool path — **Option A (python_script over a file SQLite)**.
The DAG has ONE ``llm_call`` node whose ``tool_configurations`` exposes a
``python_script`` tool (Pattern A from the python_node guide): the script ``code``
is ``fixed`` (the LLM never sees or writes it) and the LLM supplies a single
``query`` argument. The fixed script opens a file-based SQLite DB (built once from
the variant CSV) and runs the model's SELECT:

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    ... conn.execute(query).fetchall() ...
    output = {"result": <compact text table or "ERROR: ..."> }

``sandbox_mode`` is ``"none"`` so ``import sqlite3`` + ``open`` of the local DB
file are permitted (the ``restricted`` sandbox bans both and has no sqlite3 in its
import whitelist). The in-memory ``load_orders_sqlite`` helper can't be reused
because the python_script runs in a fresh interpreter inside the engine process —
it needs a path on disk, so we build ``/tmp/orders_<variant>.db`` from the CSV.

Engine env mirrors task05's ``_ensure_env`` (proxy key, Postgres URL for the
llm_call ``connection_url``, durable storage dir).
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from bench_common import (
    RunnerArgs, variant_params, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _ensure_env(caller: Any) -> None:
    """Env the engine needs at run_dag time: proxy key, Postgres URL, durable storage."""
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    if not os.environ.get("SECURE_VALUES_KEY"):
        # 32-byte key the engine expects for secure-value handling; any stable
        # value works for a single local run (mirrors task05's expectations).
        os.environ["SECURE_VALUES_KEY"] = "0" * 64
    if not os.environ.get("COLMENA_LOCAL_STORAGE_DIR"):
        storage_dir = Path("/tmp") / "colmena-bench-storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        os.environ["COLMENA_LOCAL_STORAGE_DIR"] = str(storage_dir)
        os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")


def _build_sqlite_file(csv_path: Path, variant: str) -> Path:
    """Build a file-based SQLite DB with an `orders` table from the CSV.

    Mirrors bench_common.load_orders_sqlite (all columns TEXT) but writes to a
    file the engine's python_script can open. Rebuilt fresh each run so a stale
    file never masks a dataset change.
    """
    db_path = Path("/tmp") / f"orders_{variant}.db"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        cols = ", ".join(f'"{c}" TEXT' for c in header)
        conn.execute(f"CREATE TABLE orders ({cols})")
        placeholders = ", ".join("?" for _ in header)
        conn.executemany(f"INSERT INTO orders VALUES ({placeholders})", reader)
    conn.commit()
    conn.close()
    return db_path


# Fixed python_script body. Runs read-only: opens the DB file, executes the
# model-provided `query`, returns a compact text table (capped) or an ERROR
# string the model can read and recover from. `{DB_PATH}` is stamped at build
# time. `query` arrives as an injected global from the LLM tool call.
_TOOL_CODE = """
import sqlite3
conn = sqlite3.connect("{DB_PATH}")
try:
    cur = conn.execute(query)
    rows = cur.fetchall()
    names = [d[0] for d in cur.description] if cur.description else []
    lines = [" | ".join(names)] if names else []
    for r in rows[:200]:
        lines.append(" | ".join("" if v is None else str(v) for v in r))
    if len(rows) > 200:
        lines.append("... (" + str(len(rows)) + " rows total, showing 200)")
    result = "\\n".join(lines) if lines else "(no rows)"
except Exception as e:
    result = "ERROR: " + type(e).__name__ + ": " + str(e)
finally:
    conn.close()
output = {{"result": result}}
""".strip()


def _build_dag(model_alias: str, db_path: Path, prompt: str) -> dict[str, Any]:
    """One llm_call node with a run_sql python_script tool (Pattern A: fixed code)."""
    return {
        "nodes": {
            "trigger": {"type": "trigger_webhook", "config": {"path": "/ask"}},
            "assistant": {
                "type": "llm_call",
                "config": {
                    "provider": "openai",
                    "model": model_alias,
                    "api_key": "${OPENAI_API_KEY}",
                    "connection_url": "${DATABASE_URL}",
                    "temperature": 0.0,
                    "stream": False,
                    "max_tokens": 8000,
                    "system_message": (
                        "You are a data analyst. For every fact you need, call the "
                        "run_sql tool with a SQLite SELECT over the `orders` table "
                        "(all columns TEXT — CAST(... AS REAL/INTEGER) for math). "
                        "Call it as many times as needed. Never compute from memory."
                    ),
                    "tool_configurations": {
                        "run_sql": {
                            "name": "run_sql",
                            "node_type": "python_script",
                            "description": (
                                "Run a read-only SQL SELECT against the `orders` "
                                "table and return the rows as a text table."
                            ),
                            "node_schema": {
                                "sandbox_mode": {"type": "string", "fixed": "none"},
                                "code": {
                                    "type": "string",
                                    "fixed": _TOOL_CODE.format(DB_PATH=str(db_path)),
                                },
                                "query": {
                                    "type": "string",
                                    "required": True,
                                    "description": (
                                        "A single read-only SQLite SELECT statement "
                                        "over the `orders` table."
                                    ),
                                },
                            },
                        }
                    },
                },
            },
            "log": {"type": "log"},
        },
        "edges": [
            {"from": "trigger", "to": "assistant"},
            {"from": "assistant", "to": "log"},
        ],
    }


def run(task_def: dict[str, Any], caller: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    import colmena

    _ensure_env(caller)
    vp = variant_params(task_def, args.variant)
    db_path = _build_sqlite_file(REPO_ROOT / vp["dataset_path"], args.variant)
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)
    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}"

    dag = _build_dag(caller.model_alias, db_path, prompt)
    session_id = f"t4exp_{args.run_id}"
    result_json = colmena.run_dag(dag, None, None, {"prompt": prompt}, True, session_id)
    node_out = json.loads(result_json).get("assistant", {})
    text = node_out.get("result", "") if isinstance(node_out, dict) else str(node_out)

    answer = extract_answer_dict(str(text))
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
