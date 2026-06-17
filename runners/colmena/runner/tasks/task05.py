"""Task 5 — Colmena context-scrubbing demo (Hero Demo #1, "context tax").

The agent IS the DAG: a single ``trigger_webhook → llm_call(assistant) → log``
graph, built ONCE. Each of the 10 turns just feeds that turn's user message
through ``inject_payload={"prompt": ...}`` — the ``llm_call`` node sources its
prompt from the trigger payload (``inputs["prompt"]`` takes priority over
``config.prompt``; see colmena llm.rs). All turns share ONE stable
``agent_session_id`` and the same node id (``assistant``), so Colmena's
conversation memory — keyed by ``(agent_session_id, node_id)`` — carries history
across runs. No per-turn templating, no JSON reload, no nested-key stamping.

Why Colmena stays flat on the token asymptote:

* The Q3 report is attached via ``files[]`` ONLY on turn 0 (the static DAG). The
  engine registers it in the session attachment catalog but does NOT inject the
  bytes into context — the model calls ``load_attachment`` when it needs the
  content. Later turns read it from the persisted catalog without re-attaching.
* The ``generate_chart`` tool returns a ~32KB base64 PNG data URI. Colmena's
  always-on tool-output scrubber (dag_tool_executor.rs ``scrub_value_for_llm``)
  elides any ``data:<mime>;base64,...`` string to ``[binary elided: ...]`` before
  it reaches the LLM context, so chart turns do not bloat input tokens.

Token accounting is done by the proxy spans (bucketed per turn via
``extras.turn_boundaries``), so ``usage`` here is all zeros by contract.

Cross-turn ``load_attachment`` needs durable cross-process byte storage
(each turn is a separate ``run_dag`` process) — see ``_ensure_env``
(``COLMENA_LOCAL_STORAGE_DIR``).
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench_common import (
    RunnerArgs,
    REPORT_TEXT,
    REPORT_DOC_ID,
    REPORT_FILENAME,
    TURNS,
    SYSTEM_MESSAGE,
    generate_chart,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_env(caller: Any) -> None:
    """Env the engine needs at run_dag time: proxy key, Postgres URL, durable storage."""
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    if not os.environ.get("COLMENA_LOCAL_STORAGE_DIR"):
        storage_dir = Path("/tmp") / "colmena-bench-storage"
        storage_dir.mkdir(parents=True, exist_ok=True)
        os.environ["COLMENA_LOCAL_STORAGE_DIR"] = str(storage_dir)
        os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")


def _build_dag(model_alias: str, chart_data_uri: str) -> dict[str, Any]:
    """The whole agent, built once. Per-turn prompt arrives via inject_payload."""
    report_b64 = base64.b64encode(REPORT_TEXT.encode("utf-8")).decode("ascii")
    return {
        "nodes": {
            "trigger": {"type": "trigger_webhook", "config": {"path": "/turn"}},
            "assistant": {"type": "llm_call", "config": {
                "provider": "openai", "model": model_alias, "api_key": "${OPENAI_API_KEY}",
                "connection_url": "${DATABASE_URL}", "attachments_enabled": True,
                "temperature": 0.0, "stream": False, "system_message": SYSTEM_MESSAGE,
                "files": [{"id": REPORT_DOC_ID, "filename": REPORT_FILENAME,
                           "mime_type": "text/markdown", "label": "Q3 2026 Business Review",
                           "data": f"data:text/markdown;base64,{report_b64}"}],
                "tool_configurations": {"generate_chart": {
                    "name": "generate_chart", "node_type": "python_script",
                    "description": "Generate a chart image from a natural-language description. Returns the chart as a base64 PNG data URI.",
                    "node_schema": {
                        "sandbox_mode": {"type": "string", "fixed": "none"},
                        "code": {"type": "string", "fixed": 'output = {"chart": chart_data_uri}'},
                        "chart_data_uri": {"type": "string", "fixed": chart_data_uri},
                        "description": {"type": "string", "required": True,
                                        "description": "Natural-language description of the chart to generate."}}}}}},
            "log": {"type": "log"},
        },
        "edges": [{"from": "trigger", "to": "assistant"}, {"from": "assistant", "to": "log"}],
    }


def run(
    task_def: dict[str, Any], caller: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    import colmena

    _ensure_env(caller)
    session_id = f"demo05_{args.run_id}"
    dag = _build_dag(caller.model_alias, generate_chart(""))

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]
    for i, turn in enumerate(TURNS):
        try:
            if i == 1:  # report attached only on turn 0; drop it for the rest
                dag["nodes"]["assistant"]["config"].pop("files", None)
            result_json = colmena.run_dag(
                dag, None, None, {"prompt": turn["message"]}, True, session_id
            )
            node_out = json.loads(result_json).get("assistant", {})
            text = node_out.get("result", "") if isinstance(node_out, dict) else str(node_out)
            answers.append(str(text))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            answers.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")
        finally:
            turn_boundaries.append(_now_iso())

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, usage, extras
