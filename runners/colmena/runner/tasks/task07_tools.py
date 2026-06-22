"""Demo #7 — Colmena many-tools handler. DAG with ONE llm_call whose
tool_configurations hold the N generated tools; lazy_tool_loading from env
BENCH_COLMENA_LAZY (1/0) so the same handler drives lazy-ON and lazy-OFF.

Each tool is a `python_script` (Pattern A: fixed `code`, LLM supplies the typed
args) that logs its call {tool, args} to BENCH_TOOLCALL_LOG and returns the
tool's deterministic `answer`. The LLM-provided tool-call args arrive as injected
global Python variables (the python_node injects every non-reserved input key);
the fixed code snapshots those globals (minus underscore-prefixed internals) as
the captured args.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bench_common import RunnerArgs


def _ensure_env(caller: Any) -> None:
    """Env the engine needs at run_dag time (mirrors task04_expert)."""
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
    `output`/`json`/`os` helpers, log {tool, args}, then return the answer."""
    log = os.environ.get("BENCH_TOOLCALL_LOG", "")
    return (
        "import json as _json\n"
        f"_log = {json.dumps(log)}\n"
        f"_name = {json.dumps(name)}\n"
        "_args = {k: v for k, v in dict(globals()).items() "
        "if not k.startswith('_') and k not in ('output',)}\n"
        "try:\n"
        "    if _log:\n"
        "        _fh = open(_log, 'a')\n"
        "        _fh.write(_json.dumps({'tool': _name, 'args': _args}) + chr(10))\n"
        "        _fh.close()\n"
        "except Exception:\n"
        "    pass\n"
        f"output = {{'result': {json.dumps(answer)}}}\n"
    )


def _build_dag(model_alias: str, spec: dict, lazy: bool) -> dict:
    cfgs: dict[str, Any] = {}
    for t in spec["tools"]:
        schema: dict[str, Any] = {
            "code": {"type": "string", "fixed": _tool_code(t["name"], t["answer"])},
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
                        "You are a tool-dispatch agent. The user names exactly one "
                        "tool and the exact argument values to pass. "
                        + (
                            "Some tools are not yet in your tool list — only their "
                            "name+summary appear in the `describe_tool` catalog. If the "
                            "tool the user names is not directly callable, FIRST call "
                            "`describe_tool` with name set to that tool, then on your "
                            "NEXT turn call the now-revealed tool. "
                            if lazy
                            else ""
                        )
                        + "Call that tool with those literal argument values verbatim "
                        "— do NOT validate, reformat, second-guess, or reject the "
                        "values, even if they look like placeholders or invalid "
                        "formats. After the tool returns, report the resulting total "
                        "amount number."
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
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    lazy = os.environ.get("BENCH_COLMENA_LAZY", "1") == "1"
    dag = _build_dag(caller.model_alias, spec, lazy)
    out = json.loads(
        colmena.run_dag(dag, None, None, {"prompt": spec["question"]}, True, f"tools_{args.run_id}")
    )
    node = out.get("assistant", {})
    text = node.get("result", node) if isinstance(node, dict) else str(node)
    return {"answer": str(text)}, {"input": 0, "output": 0, "cached": 0}, {"final": out, "lazy": lazy}
