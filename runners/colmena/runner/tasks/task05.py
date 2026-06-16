"""Task 5 — Colmena context-scrubbing demo (Hero Demo #1, "context tax").

Replays the fixed 10-turn conversation from ``bench_common.scenario05`` as a
sequence of ``colmena.run_dag`` calls that all share ONE stable
``agent_session_id``. Each turn is a single ``llm_call`` node whose node id is
stable (``assistant``) so Colmena's conversation memory — keyed by
``(agent_session_id, node_id)`` (see colmena docs 15_memory_guide.md) — carries
the history across runs.

Why Colmena stays flat on the token asymptote:

* The Q3 report is attached via ``files[]`` ONLY on turn 0. Colmena registers it
  in the session's attachment catalog (Plan A/B) but does NOT inject the bytes
  into the LLM context — the model calls ``load_attachment`` when it actually
  needs the content, and that content is ephemeral (only for that turn). Later
  turns rely on the persisted catalog without re-attaching.
* The ``generate_chart`` tool returns a ~32KB base64 PNG data URI. Colmena's
  always-on tool-output scrubber (dag_tool_executor.rs ``scrub_value_for_llm``)
  replaces any ``data:<mime>;base64,...`` string with a compact
  ``[binary elided: ...]`` marker before it ever reaches the LLM context, so
  chart turns do not bloat input tokens on subsequent turns.

Token accounting is done by the proxy spans (the orchestrator buckets them per
turn using the ``turn_boundaries`` timestamps in ``extras``), so ``usage`` here
is all zeros by contract.

KNOWN LIMITATION (engine, not this handler) — attachment via the proxy:
  Colmena's ``FileProviderFactory::create`` (src/libs/colmena/.../files/
  file_provider_factory.rs) builds ``OpenAiFilesApiAdapter::new(api_key)`` which
  HARDCODES ``base_url = "https://api.openai.com"`` and ignores
  ``OPENAI_BASE_URL``. So every ``files[]`` entry is uploaded to the real OpenAI
  Files API, NOT through the LiteLLM proxy. With the proxy master key as the
  bearer that upload is rejected and the node fails with "all files in the
  request failed to materialize", so turn 0 errors and the doc turns answer
  "please provide the report". The api_key is coupled across the chat call (proxy)
  and the file upload (api.openai.com), so no single key satisfies both. The
  engine exposes ``OpenAiFilesApiAdapter::with_base_url`` but the factory never
  uses it — wiring it to ``OPENAI_BASE_URL`` would unblock the attachment half.
  The chart-scrubbing half works fully through the proxy (verified: chart turns
  add no ~30KB base64 to input tokens).
"""
from __future__ import annotations

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

_DAG_TEMPLATE = Path(__file__).resolve().parent.parent.parent / "dags" / "demo05_turn.json"


def _now_iso() -> str:
    """ISO-8601 UTC timestamp with a trailing 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_env(caller: Any) -> None:
    """Set the env the Colmena engine needs at run_dag time.

    * ``OPENAI_API_KEY`` — the DAG's ``${OPENAI_API_KEY}`` placeholder resolves
      from env; it MUST be the proxy key. ``OPENAI_BASE_URL`` is already set by
      ``build_llm`` when it constructed the ColmenaLlm.
    * ``DATABASE_URL`` — the engine needs Postgres for memory/attachments. The
      repo names it ``COLMENA_DATABASE_URL`` (so the proxy doesn't auto-load it);
      copy it over if ``DATABASE_URL`` isn't already set.
    """
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL"):
        colmena_db = os.environ.get("COLMENA_DATABASE_URL")
        if colmena_db:
            os.environ["DATABASE_URL"] = colmena_db


def _build_dag(
    *,
    model_alias: str,
    system_message: str,
    prompt: str,
    chart_data_uri: str,
    attach_report: bool,
) -> dict[str, Any]:
    """Load the JSON template and fill it for one turn.

    We build a dict (not string replacement) so the ~32KB chart data URI and the
    full report text never have to survive JSON-string escaping. ``${...}``
    placeholders that resolve from the engine's env (OPENAI_API_KEY, DATABASE_URL)
    are left intact for the engine to substitute.
    """
    dag = json.loads(_DAG_TEMPLATE.read_text())
    dag.pop("_comment", None)

    cfg = dag["nodes"]["assistant"]["config"]
    cfg["model"] = model_alias
    cfg["system_message"] = system_message
    cfg["prompt"] = prompt
    cfg["tool_configurations"]["generate_chart"]["node_schema"]["chart_data_uri"][
        "fixed"
    ] = chart_data_uri

    if attach_report:
        cfg["files"] = [
            {
                "id": REPORT_DOC_ID,
                "filename": REPORT_FILENAME,
                "mime_type": "text/markdown",
                "label": "Q3 2026 Business Review",
                # Inline text content. The engine's `files[].data` field accepts a
                # `data:` URI (it strips the `data:<mime>;base64,` prefix and
                # base64-decodes the rest — see llm.rs build_file_source). This is
                # the inline form (FileSource::InlineBytes); `url` is for fetchable
                # signed URLs only and would fail to materialize for inline text.
                "data": _inline_text_data_uri(REPORT_TEXT),
            }
        ]
    return dag


def _inline_text_data_uri(text: str) -> str:
    import base64

    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"data:text/markdown;base64,{b64}"


def run(
    task_def: dict[str, Any], caller: Any, args: RunnerArgs
) -> tuple[list[str], dict[str, int], dict[str, Any]]:
    import colmena

    _ensure_env(caller)

    session_id = f"demo05_{args.run_id}"
    chart_data_uri = generate_chart("")

    answers: list[str] = []
    turn_boundaries: list[str] = [_now_iso()]  # boundary BEFORE turn 0

    for i, turn in enumerate(TURNS):
        try:
            dag = _build_dag(
                model_alias=caller.model_alias,
                system_message=SYSTEM_MESSAGE,
                prompt=turn["message"],
                chart_data_uri=chart_data_uri,
                attach_report=(i == 0),
            )
            result_json = colmena.run_dag(dag, None, None, None, True, session_id)
            result = json.loads(result_json)
            node_out = result.get("assistant", {})
            if isinstance(node_out, dict):
                text = node_out.get("result", "")
            else:
                text = str(node_out)
            answers.append(str(text))
        except Exception as e:  # noqa: BLE001 — one bad turn must not sink the run
            answers.append(f"[ERROR turn {i}: {type(e).__name__}: {e}]")
        finally:
            turn_boundaries.append(_now_iso())  # boundary AFTER this turn

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {
        "turn_boundaries": turn_boundaries,
        "turn_types": [t["type"] for t in TURNS],
    }
    return answers, usage, extras
