"""Tests the runner's output-emission path without requiring CrewAI or keys.

Goal: prove that a runner that produces a (answer, usage) tuple writes a
file that validates against run_output.schema.json. Real CrewAI integration
is exercised by `scripts/verify_baseline.sh` (T11) once API keys land.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

RUNNER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER_DIR))

from runner.common import RunnerArgs, emit_output, score_success  # noqa: E402

REPO_ROOT = RUNNER_DIR.parent.parent
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
    started = datetime.now(timezone.utc)
    ended = datetime.now(timezone.utc)
    emit_output(
        args,
        started_at=started,
        ended_at=ended,
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
    assert payload["success"]["ok"] is True
    assert payload["run_id"] == args.run_id


def test_score_success_regex_negative():
    res = score_success({"kind": "regex", "pattern": r"(?i)\bhello\b"}, "goodbye")
    assert res["ok"] is False


def test_emit_records_error_path(tmp_path):
    args = _args(tmp_path)
    now = datetime.now(timezone.utc)
    emit_output(
        args,
        started_at=now,
        ended_at=now,
        cold_start_ms=5,
        answer=None,
        tokens_input=0,
        tokens_output=0,
        tokens_cached=0,
        tool_calls=0,
        success={"ok": False, "reason": "boom"},
        error="RuntimeError: boom",
    )
    payload = json.loads(args.output.read_text())
    Draft202012Validator(SCHEMA).validate(payload)
    assert payload["error"] == "RuntimeError: boom"
    assert payload["success"]["ok"] is False
