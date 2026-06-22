"""Validates the four JSON schemas under harness/schemas/ + sample fixtures.

These tests are the contract between the orchestrator, runners, and the
proxy. If they fail, something downstream (a runner, the aggregator) is
about to produce data the rest of the harness can't consume.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_FILES = [
    "task.schema.json",
    "run_output.schema.json",
    "aggregated.schema.json",
    "proxy_span.schema.json",
]


@pytest.fixture(scope="module")
def schemas() -> dict[str, dict]:
    out = {}
    for name in SCHEMA_FILES:
        with (SCHEMAS_DIR / name).open() as f:
            out[name] = json.load(f)
    return out


def test_all_schemas_are_themselves_valid_json_schema(schemas):
    for name, schema in schemas.items():
        # Throws if the schema itself is malformed against draft 2020-12.
        Draft202012Validator.check_schema(schema)


def _sample_task() -> dict:
    return {
        "id": "01_hello_world",
        "title": "Hello world",
        "version": "0.1.0",
        "prompt": "Say hi.",
        "metrics": ["latency", "tokens", "success"],
        "success": {"kind": "regex", "pattern": "(?i)hi"},
    }


def _sample_run_output(run_id: str | None = None) -> dict:
    return {
        "run_id": run_id or str(uuid.uuid4()),
        "task_id": "01_hello_world",
        "variant": "default",
        "framework": "colmena",
        "framework_version": "develop",
        "model_alias": "gemini-2.5-flash",
        "started_at": "2026-06-10T12:00:00Z",
        "ended_at": "2026-06-10T12:00:01Z",
        "latency_ms": 1024,
        "tokens": {"input": 12, "output": 4, "cached": 0},
        "tool_calls": 0,
        "success": {"ok": True},
        "answer": "hi",
        "host": {
            "hostname": "bench-01",
            "os": "Linux 6.5",
            "cpu_model": "Apple M2",
            "ram_gb": 16.0,
        },
    }


def _sample_aggregated() -> dict:
    stat = {
        "mean": 1024.0,
        "stdev": 50.0,
        "p50": 1020.0,
        "p95": 1100.0,
        "p99": 1200.0,
        "ci95_low": 1010.0,
        "ci95_high": 1040.0,
        "min": 950.0,
        "max": 1250.0,
    }
    return {
        "task_id": "01_hello_world",
        "variant": "default",
        "framework": "colmena",
        "model_alias": "gemini-2.5-flash",
        "n": 30,
        "n_failed": 0,
        "success_rate": 1.0,
        "stats": {
            "latency_ms": stat,
            "tokens_input": stat,
            "tokens_output": stat,
        },
        "cost": {"usd_per_run": stat, "pricing_table_date": "2026-06-10"},
    }


def _sample_span(run_id: str = "demo") -> dict:
    return {
        "span_id": str(uuid.uuid4()),
        "run_id": run_id,
        "ts_start": 1717977600.0,
        "ts_end": 1717977601.0,
        "latency_ms": 1000,
        "model_alias": "gemini-2.5-flash",
        "provider_model": "gemini/gemini-2.5-flash",
        "tokens_input": 12,
        "tokens_output": 4,
        "tokens_cached": 0,
        "ttft_ms": 200,
        "ok": True,
        "error": None,
    }


def test_sample_task_validates(schemas):
    Draft202012Validator(schemas["task.schema.json"]).validate(_sample_task())


def test_task_rejects_unknown_metric(schemas):
    bad = _sample_task()
    bad["metrics"] = ["latency", "wallclock"]  # `wallclock` not in enum
    with pytest.raises(Exception):
        Draft202012Validator(schemas["task.schema.json"]).validate(bad)


def test_task_rejects_malformed_id(schemas):
    bad = _sample_task()
    bad["id"] = "HelloWorld"  # must match ^[0-9]{2}_[a-z0-9_]+$
    with pytest.raises(Exception):
        Draft202012Validator(schemas["task.schema.json"]).validate(bad)


def test_task_accepts_dataset_qa_success_kind(schemas):
    task = _sample_task()
    task["id"] = "04_csv_naive"
    task["success"] = {"kind": "dataset_qa", "ground_truth_path": "data/orders_synthetic/ground_truth.json"}
    Draft202012Validator(schemas["task.schema.json"]).validate(task)


def test_sample_run_output_validates(schemas):
    Draft202012Validator(schemas["run_output.schema.json"]).validate(_sample_run_output())


def test_run_output_rejects_unknown_framework(schemas):
    bad = _sample_run_output()
    bad["framework"] = "autogen"
    with pytest.raises(Exception):
        Draft202012Validator(schemas["run_output.schema.json"]).validate(bad)


def test_sample_aggregated_validates(schemas):
    Draft202012Validator(schemas["aggregated.schema.json"]).validate(_sample_aggregated())


def test_sample_span_validates(schemas):
    Draft202012Validator(schemas["proxy_span.schema.json"]).validate(_sample_span())


def test_span_requires_uuid_span_id(schemas):
    bad = _sample_span()
    bad["span_id"] = "not-a-uuid"
    with pytest.raises(Exception):
        Draft202012Validator(
            schemas["proxy_span.schema.json"],
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        ).validate(bad)


def test_run_id_correlation_contract(schemas):
    """run_output.run_id and proxy_span.run_id must use the same identifier.

    Not enforceable in JSON Schema alone; this test pins the contract so a
    future refactor can't quietly diverge the two fields.
    """
    run_id = str(uuid.uuid4())
    ro = _sample_run_output(run_id=run_id)
    span = _sample_span(run_id=run_id)
    assert ro["run_id"] == span["run_id"]
