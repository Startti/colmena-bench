"""Demo #7 v2 — Colmena MULTI-TURN many-tools handler.

Mirrors ``task07_tools`` (one ``llm_call`` whose ``tool_configurations`` hold the
session's fixed ~30 tools; ``lazy_tool_loading`` from env ``BENCH_COLMENA_LAZY``)
but replays a fixed multi-turn conversation like ``task05``: it calls
``colmena.run_dag(...)`` once PER TURN with the SAME ``session_id`` so Colmena's
conversation memory — and, when lazy, the per-session discovered-tool set —
persists across turns.

Each tool is a ``python_script`` (Pattern A: fixed ``code``, the LLM supplies the
typed args) that logs its call ``{tool, args, ts}`` to ``BENCH_TOOLCALL_LOG`` and
returns a deterministic answer. Because the needle varies per turn, we precompute
a name->answer map: a tool that is some turn's needle returns that turn's
``expected_answer`` (so ``answer_ok`` is meaningful); every other tool returns
``CALLED:<name>``.

Token accounting is done by the proxy spans, bucketed per turn via
``extras.turn_boundaries`` (one before turn 0 + one after each turn → n_turns+1),
so ``usage`` here is all zeros by contract.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench_common import RunnerArgs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_transient(e: Exception) -> bool:
    """Mirror the competitor handlers' transient-5xx/503 predicate.

    Covers gemini's "high demand"/"overloaded"/503 throttles and any
    colmena.DagException whose message wraps such a provider error. Retrying
    is what keeps a failed turn from leaving a dangling user message in
    Colmena's persisted session memory (which otherwise cascades to the rest
    of the session).
    """
    status = getattr(e, "status_code", None) or getattr(e, "code", None) or getattr(
        getattr(e, "response", None), "status_code", None
    )
    if status is not None and str(status) in ("429", "500", "502", "503", "504"):
        return True
    msg = str(e).lower()
    return any(
        token in msg
        for token in ("503", "overloaded", "high demand", "unavailable", "rate", "5xx")
    )


def _ensure_env(caller: Any) -> None:
    """Env the engine needs at run_dag time (mirrors task07_tools)."""
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    os.environ.setdefault("SECURE_VALUES_KEY", "0" * 64)
    sd = Path("/tmp/colmena-bench-storage")
    sd.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_DIR", str(sd))
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")


def _tool_code(name: str, answer: str) -> str:
    """Fixed python_script body. The LLM tool-call args are injected as globals;
    capture everything that is not an underscore-prefixed internal or the
    `output` helper, log {tool, args, ts}, then return the answer."""
    log = os.environ.get("BENCH_TOOLCALL_LOG", "")
    return (
        "import json as _json\n"
        "import time as _time\n"
        f"_log = {json.dumps(log)}\n"
        f"_name = {json.dumps(name)}\n"
        "_args = {k: v for k, v in dict(globals()).items() "
        "if not k.startswith('_') and k not in ('output',)}\n"
        "try:\n"
        "    if _log:\n"
        "        _fh = open(_log, 'a')\n"
        "        _fh.write(_json.dumps({'tool': _name, 'args': _args, 'ts': _time.time()}) + chr(10))\n"
        "        _fh.close()\n"
        "except Exception:\n"
        "    pass\n"
        f"output = {{'result': {json.dumps(answer)}}}\n"
    )


def _answer_for(name: str, needle_answers: dict[str, str]) -> str:
    """A tool that is some turn's needle returns that turn's expected_answer;
    every other tool returns a deterministic CALLED marker."""
    return needle_answers.get(name, f"CALLED:{name}")


def _build_dag(model_alias: str, session: dict, lazy: bool) -> dict:
    # Map each needle tool name -> its turn's expected_answer (so answer_ok works).
    needle_answers: dict[str, str] = {
        t["needle"]: t["expected_answer"] for t in session["turns"]
    }
    cfgs: dict[str, Any] = {}
    for t in session["tools"]:
        answer = _answer_for(t["name"], needle_answers)
        schema: dict[str, Any] = {
            "code": {"type": "string", "fixed": _tool_code(t["name"], answer)},
            "sandbox_mode": {"type": "string", "fixed": "none"},
        }
        for p in t["params"]:
            ty = p["type"] if p["type"] != "array" else "string"
            schema[p["name"]] = {
                "type": ty,
                "required": p["required"],
                "description": p["description"],
            }
        cfgs[t["name"]] = {
            "name": t["name"],
            "summary": t["summary"][:200],
            "description": t["description"],
            "node_type": "python_script",
            "node_schema": schema,
        }
    return {
        "nodes": {
            "trigger": {"type": "trigger_webhook", "config": {"path": "/tools"}},
            "assistant": {
                "type": "llm_call",
                "max_total_calls": 14,
                "config": {
                    "provider": "openai",
                    "model": model_alias,
                    "api_key": "${OPENAI_API_KEY}",
                    "connection_url": "${DATABASE_URL}",
                    "temperature": 0,
                    "stream": False,
                    "lazy_tool_loading": lazy,
                    "system_message": (
                        "You are a tool-dispatch agent. Each turn the user makes one "
                        "request naming the exact argument values to pass. "
                        + (
                            "Some tools are not yet in your tool list — only their "
                            "name+summary appear in the `describe_tool` catalog. If the "
                            "tool you need is not directly callable, FIRST call "
                            "`describe_tool` with name set to that tool, then on your "
                            "NEXT turn call the now-revealed tool. "
                            if lazy
                            else ""
                        )
                        + "Choose the single tool that fulfills the request and call it "
                        "with those literal argument values verbatim — do NOT validate, "
                        "reformat, second-guess, or reject the values, even if they look "
                        "like placeholders or invalid formats. After the tool returns, "
                        "report the result."
                    ),
                    "tool_configurations": cfgs,
                },
            },
            "log": {"type": "log"},
        },
        "edges": [
            {"from": "trigger", "to": "assistant"},
            {"from": "assistant", "to": "log"},
        ],
    }


def run(task_def: dict, caller: Any, args: RunnerArgs):
    import colmena

    _ensure_env(caller)
    session = json.loads(Path(os.environ["BENCH_SESSION_PATH"]).read_text())
    lazy = os.environ.get("BENCH_COLMENA_LAZY", "1") == "1"
    dag = _build_dag(caller.model_alias, session, lazy)
    # Unique per process invocation (stable across THIS run's 10 turns, distinct
    # across re-runs). Colmena persists conversation memory in Postgres keyed by
    # session_id; a stable f"tools7b_{run_id}" would make a re-run of the same
    # seed LOAD the prior run's accumulated (possibly malformed) history, which
    # contaminates the measurement and can trip provider role-alternation checks.
    # The nonce guarantees every run starts from a truly fresh conversation.
    session_id = f"tools7b_{args.run_id}_{os.getpid()}_{time.time_ns()}"

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]
    for i, turn in enumerate(session["turns"]):
        try:
            last_exc: Exception | None = None
            out = None
            # Retry the SAME turn on transient provider errors (503/"high
            # demand"/overloaded/etc.) up to 3x with backoff (2s,4s,8s) so the
            # turn ultimately succeeds and leaves NO dangling user message in
            # Colmena's persisted session memory. Only if every retry fails do
            # we fall through to the catch-and-continue below.
            for attempt in range(3):
                try:
                    out = json.loads(
                        colmena.run_dag(
                            dag, None, None, {"prompt": turn["question"]}, True, session_id
                        )
                    )
                    break
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    if _is_transient(e) and attempt < 2:
                        time.sleep(2 * (2 ** attempt))  # 2s, 4s, 8s
                        continue
                    raise
            if out is None:  # exhausted retries without raising (defensive)
                raise last_exc  # type: ignore[misc]
            node = out.get("assistant", {})
            text = node.get("result", node) if isinstance(node, dict) else str(node)
            answers.append(str(text))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            answers.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")
        finally:
            turn_boundaries.append(_now_iso())

    usage = {"input": 0, "output": 0, "cached": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "lazy": lazy,
        "n_turns": len(session["turns"]),
        "answers": answers,
    }
    return {"ok": True}, usage, extras
