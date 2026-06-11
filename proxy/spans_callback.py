"""LiteLLM callback that writes one JSONL line per LLM call.

Schema is defined in `harness/schemas/proxy_span.schema.json` (T05) and is the
source of truth for token / cost metrics — see METHODOLOGY §4.

Loaded by the LiteLLM proxy via `litellm_settings.callbacks` in
`litellm_config.yaml` (entry: `spans_callback.spans_jsonl`). Path resolution:

    proxy/spans/run-<BENCH_RUN_ID>.jsonl

`BENCH_RUN_ID` is set by `scripts/run_task.sh` per benchmark run so each run
gets its own append-only file. If unset (e.g. ad-hoc curl), spans go to
`proxy/spans/run-adhoc.jsonl`.

This file is loaded at proxy start-up, not at install time. It must be
self-contained — no relative imports.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from litellm.integrations.custom_logger import CustomLogger


def _spans_dir() -> Path:
    base = Path(os.environ.get("LITELLM_SPANS_DIR", "./proxy/spans")).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _spans_path(run_id: str) -> Path:
    return _spans_dir() / f"run-{run_id}.jsonl"


def _run_id_for_call(kwargs: dict) -> str:
    """Per-call run id, so a long-lived proxy routes spans to per-run files.

    Priority: the `x-bench-run-id` request header (set by every runner) →
    `BENCH_RUN_ID` env (set when the proxy is started for one run) → "adhoc".
    """
    lp = kwargs.get("litellm_params") or {}
    psr = lp.get("proxy_server_request") or kwargs.get("proxy_server_request") or {}
    headers = psr.get("headers") if isinstance(psr, dict) else None
    if headers:
        # Header names are lower-cased by the ASGI server.
        rid = headers.get("x-bench-run-id") or headers.get("X-Bench-Run-Id")
        if rid:
            return str(rid)
    return os.environ.get("BENCH_RUN_ID", "adhoc")


def _attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    """Read `key` from obj whether it's a dict or an attribute-bearing object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_usage(kwargs: dict, response_obj: Any) -> tuple[int, int, int]:
    """Return (input, output, cached) tokens, trying the most stable source first."""
    # 1) standard_logging_object — stable, present in the proxy path.
    slo = kwargs.get("standard_logging_object") or {}
    ti = slo.get("prompt_tokens")
    to = slo.get("completion_tokens")
    if ti is not None or to is not None:
        cached = slo.get("cache_read_input_tokens") or 0
        return int(ti or 0), int(to or 0), int(cached)

    # 2) response_obj.usage (ModelResponse object or dict).
    usage = _attr_or_key(response_obj, "usage")
    if usage is not None:
        ti = _attr_or_key(usage, "prompt_tokens", 0) or 0
        to = _attr_or_key(usage, "completion_tokens", 0) or 0
        ptd = _attr_or_key(usage, "prompt_tokens_details")
        cached = _attr_or_key(ptd, "cached_tokens", 0) or 0
        return int(ti), int(to), int(cached)

    return 0, 0, 0


class SpansJsonl(CustomLogger):
    """Append one JSONL span per call to a per-run file.

    Deduped on `litellm_call_id`: the proxy can fire both the sync and async
    success hooks for a single call, which would otherwise double-count
    tokens. We keep a bounded LRU of seen call ids.
    """

    def __init__(self, max_seen: int = 10000) -> None:
        super().__init__()
        self._seen: "OrderedDict[str, None]" = OrderedDict()
        self._max_seen = max_seen

    def _already_emitted(self, call_id: str | None) -> bool:
        if not call_id:
            return False
        if call_id in self._seen:
            return True
        self._seen[call_id] = None
        if len(self._seen) > self._max_seen:
            self._seen.popitem(last=False)
        return False

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._emit(kwargs, response_obj, start_time, end_time, ok=True, error=None)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        exc = kwargs.get("exception")
        self._emit(
            kwargs, response_obj, start_time, end_time,
            ok=False, error=str(exc) if exc is not None else "unknown",
        )

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.log_success_event(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self.log_failure_event(kwargs, response_obj, start_time, end_time)

    def _emit(self, kwargs, response_obj, start_time, end_time, *, ok: bool, error):
        call_id = kwargs.get("litellm_call_id")
        if self._already_emitted(call_id):
            return

        ti, to, cached = _extract_usage(kwargs, response_obj)
        run_id = _run_id_for_call(kwargs)
        ts_start = _to_epoch(start_time)
        ts_end = _to_epoch(end_time)
        provider_model = (
            _attr_or_key(response_obj, "model")
            or kwargs.get("model")
            or ""
        )
        # The alias the caller requested (e.g. "gemini-2.5-flash") — distinct
        # from the resolved provider model.
        model_alias = (
            kwargs.get("model")
            or _attr_or_key(kwargs.get("litellm_params"), "model")
            or ""
        )
        ttft = kwargs.get("completion_start_time")
        ttft_ms = None
        if ttft is not None:
            try:
                ttft_ms = int((_to_epoch(ttft) - ts_start) * 1000)
            except Exception:  # noqa: BLE001
                ttft_ms = None

        span = {
            "span_id": str(uuid.uuid4()),
            "run_id": run_id,
            "ts_start": ts_start,
            "ts_end": ts_end,
            "latency_ms": max(0, int((ts_end - ts_start) * 1000)),
            "model_alias": model_alias,
            "provider_model": provider_model,
            "tokens_input": ti,
            "tokens_output": to,
            "tokens_cached": cached,
            "ttft_ms": ttft_ms,
            "ok": ok,
            "error": error,
        }
        with _spans_path(run_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(span, separators=(",", ":")) + "\n")


def _to_epoch(t) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    try:
        return t.timestamp()
    except AttributeError:
        return time.time()


spans_jsonl = SpansJsonl()
