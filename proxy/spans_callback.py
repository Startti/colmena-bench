"""LiteLLM callback that writes one JSONL line per LLM call.

Schema is defined in `harness/schemas/proxy_span.schema.json` (T05) and is the
source of truth for token / cost metrics — see METHODOLOGY §4.

Loaded by the LiteLLM proxy via `litellm_settings.callbacks` in
`litellm_config.yaml`. Path resolution:

    proxy/spans/run-<BENCH_RUN_ID>.jsonl

`BENCH_RUN_ID` is set by `scripts/run_task.sh` per benchmark run so each run
gets its own append-only file. If unset (e.g. ad-hoc curl), spans go to
`proxy/spans/adhoc.jsonl`.

This file is loaded at proxy start-up, not at install time. It must be
self-contained — no relative imports.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from litellm.integrations.custom_logger import CustomLogger


def _spans_path() -> Path:
    base = Path(os.environ.get("LITELLM_SPANS_DIR", "./proxy/spans")).resolve()
    base.mkdir(parents=True, exist_ok=True)
    run_id = os.environ.get("BENCH_RUN_ID", "adhoc")
    return base / f"run-{run_id}.jsonl"


def _safe_get(d: Any, *path: str, default: Any = None) -> Any:
    cur = d
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
        if cur is None:
            return default
    return cur


class SpansJsonl(CustomLogger):
    """Append one JSONL span per call to a per-run file."""

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._emit(kwargs, response_obj, start_time, end_time, ok=True, error=None)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._emit(
            kwargs,
            response_obj,
            start_time,
            end_time,
            ok=False,
            error=str(_safe_get(kwargs, "exception", default="unknown")),
        )

    # LiteLLM also calls these in async paths; route to the same emitter.
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.log_success_event(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self.log_failure_event(kwargs, response_obj, start_time, end_time)

    def _emit(self, kwargs, response_obj, start_time, end_time, *, ok: bool, error):
        usage = _safe_get(response_obj, "usage", default={}) or {}
        span = {
            "span_id": str(uuid.uuid4()),
            "run_id": os.environ.get("BENCH_RUN_ID", "adhoc"),
            "ts_start": _to_epoch(start_time),
            "ts_end": _to_epoch(end_time),
            "latency_ms": int((_to_epoch(end_time) - _to_epoch(start_time)) * 1000),
            "model_alias": _safe_get(kwargs, "model", default=""),
            "provider_model": _safe_get(kwargs, "litellm_params", "model", default=""),
            "tokens_input": int(_safe_get(usage, "prompt_tokens", default=0) or 0),
            "tokens_output": int(_safe_get(usage, "completion_tokens", default=0) or 0),
            "tokens_cached": int(
                _safe_get(usage, "prompt_tokens_details", "cached_tokens", default=0) or 0
            ),
            "ttft_ms": _safe_get(kwargs, "completion_start_time_ms", default=None),
            "ok": ok,
            "error": error,
        }
        path = _spans_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(span, separators=(",", ":")) + "\n")


def _to_epoch(t) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    # litellm passes datetime objects in newer versions
    try:
        return t.timestamp()
    except AttributeError:
        return time.time()


spans_jsonl = SpansJsonl()
