"""Tests the shared output-emission path without any framework or keys.

Proves that a runner producing a (answer, usage) tuple writes a file that
validates against run_output.schema.json. Real per-framework integration is
exercised by scripts/verify_baseline.sh.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PKG_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_DIR))

from bench_common import RunnerArgs, emit_output, score_success  # noqa: E402

REPO_ROOT = PKG_DIR.parent.parent
SCHEMA = json.loads((REPO_ROOT / "harness/schemas/run_output.schema.json").read_text())
TASK_PATH = REPO_ROOT / "harness/tasks/01_hello_world.yaml"


def _args(tmp_path: Path) -> RunnerArgs:
    return RunnerArgs(
        task=TASK_PATH,
        variant="default",
        run_id=str(uuid.uuid4()),
        model_alias="gemini-2.5-flash",
        proxy_base_url="http://127.0.0.1:4000",
        output=tmp_path / "out.json",
        timeout_seconds=30,
    )


def test_emit_output_validates_against_schema(tmp_path):
    args = _args(tmp_path)
    now = datetime.now(timezone.utc)
    emit_output(
        args,
        framework_name="crewai",
        framework_version="1.14.6",
        started_at=now,
        ended_at=now,
        cold_start_ms=12,
        answer="hello there",
        tokens_input=10,
        tokens_output=2,
        tokens_cached=0,
        tool_calls=0,
        success=score_success({"kind": "regex", "pattern": r"(?i)\bhello\b"}, "hello there"),
    )
    payload = json.loads(args.output.read_text())
    Draft202012Validator(SCHEMA).validate(payload)
    assert payload["framework"] == "crewai"
    assert payload["framework_version"] == "1.14.6"
    assert payload["success"]["ok"] is True
    assert payload["run_id"] == args.run_id


def test_emit_output_works_for_every_framework_name(tmp_path):
    # The core is framework-agnostic; the schema enum must accept all 6.
    for fw in ("colmena", "crewai", "langchain", "langgraph", "google_adk", "llamaindex"):
        args = _args(tmp_path)
        now = datetime.now(timezone.utc)
        emit_output(
            args,
            framework_name=fw,
            framework_version="x",
            started_at=now,
            ended_at=now,
            cold_start_ms=1,
            answer="hello",
            tokens_input=1,
            tokens_output=1,
            tokens_cached=0,
            tool_calls=0,
            success={"ok": True},
        )
        payload = json.loads(args.output.read_text())
        Draft202012Validator(SCHEMA).validate(payload)
        assert payload["framework"] == fw


def test_score_success_regex_negative():
    res = score_success({"kind": "regex", "pattern": r"(?i)\bhello\b"}, "goodbye")
    assert res["ok"] is False
