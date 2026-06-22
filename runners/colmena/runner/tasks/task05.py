"""Task 5 — Colmena context-scrubbing demo (Hero Demo #1, "context tax").

The agent is a DECLARATIVE DAG: ``runners/colmena/dags/demo05_turn.json`` defines
a single ``trigger_webhook → llm_call(assistant) → log`` graph. This module is a
THIN runner — it loads that JSON once, then feeds each of the 10 turns' user
message through ``inject_payload={"prompt": ...}``. The ``llm_call`` node carries
NO static ``config.prompt``; the prompt arrives per-turn via the trigger payload
(``inputs["prompt"]`` takes priority; see colmena llm.rs). All turns share ONE
stable ``agent_session_id`` and the same node id (``assistant``), so Colmena's
conversation memory — keyed by ``(agent_session_id, node_id)`` — carries history
across runs. No per-turn templating, no JSON reload, no nested-key stamping.

The JSON carries config literals: the ``system_message`` and the turn-0 Q3 report
attachment (baked-in data URI). The only value stamped from Python is the chart
data URI — replaced ONCE at load via the ``${CHART_DATA_URI}`` placeholder so the
~32KB blob stays sourced from ``bench_common.generate_chart()`` (single source of
truth). The per-turn loop does NOTHING but ``inject_payload``.

Why Colmena stays flat on the token asymptote:

* The Q3 report is attached via ``files[]`` ONLY on turn 0 (turns 1-9 drop the
  ``files`` key). The engine registers it in the session attachment catalog but
  does NOT inject the bytes into context — the model calls ``load_attachment``
  when it needs the content. Later turns read it from the persisted catalog.
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

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench_common import RunnerArgs, TURNS, generate_chart

_DAG_PATH = Path(__file__).resolve().parents[2] / "dags" / "demo05_turn.json"


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


def _load_dag(model_alias: str) -> dict[str, Any]:
    """Load the declarative agent once; stamp the two values the JSON can't carry."""
    text = _DAG_PATH.read_text()
    text = text.replace("${MODEL_ALIAS}", model_alias)
    text = text.replace("${CHART_DATA_URI}", generate_chart(""))
    return json.loads(text)


def run(
    task_def: dict[str, Any], caller: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    import colmena

    _ensure_env(caller)
    session_id = f"demo05_{args.run_id}"
    dag = _load_dag(caller.model_alias)

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
