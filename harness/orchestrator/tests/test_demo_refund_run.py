import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import demo_refund_run as d  # noqa: E402


def test_read_mask_audit_not_leaked(tmp_path):
    (tmp_path / "mask-r1.json").write_text(json.dumps({"secret_leaked": False}))
    assert d.read_mask_audit(tmp_path, "r1") is False


def test_read_mask_audit_leaked(tmp_path):
    (tmp_path / "mask-r2.json").write_text(json.dumps({"secret_leaked": True}))
    assert d.read_mask_audit(tmp_path, "r2") is True


def test_read_mask_audit_missing_returns_none(tmp_path):
    assert d.read_mask_audit(tmp_path, "nope") is None


def test_read_mask_audit_corrupt_returns_none(tmp_path):
    (tmp_path / "mask-bad.json").write_text("{not json")
    assert d.read_mask_audit(tmp_path, "bad") is None


FWS = {"colmena", "crewai", "langchain", "llamaindex", "langgraph", "google_adk"}


def test_loc_target_shapes():
    assert set(d.FRAMEWORKS) == FWS
    assert set(d.CODE_LOC_TARGETS) == FWS
    assert set(d.CONFIG_LOC_TARGETS) == FWS
    # Every framework has exactly one imperative code file.
    for fw in FWS:
        assert len(d.CODE_LOC_TARGETS[fw]) == 1
        assert d.CODE_LOC_TARGETS[fw][0].endswith("task06_refund.py")


def test_colmena_has_config_competitors_have_none():
    # Colmena's agent is a declarative DAG -> exactly one config target.
    assert d.CONFIG_LOC_TARGETS["colmena"] == [
        "runners/colmena/runner/dags/refund_agent.json"
    ]
    # Competitors express the agent in imperative code -> no config file.
    for fw in ("crewai", "langchain", "llamaindex", "langgraph", "google_adk"):
        assert d.CONFIG_LOC_TARGETS[fw] == []


def test_new_frameworks_header_capable():
    # langgraph + google_adk forward x-bench-run-id, so their masking audit is
    # keyed by run_id (mask-<run_id>.json), not the session file.
    for fw in ("langgraph", "google_adk"):
        assert fw in d.HEADER_CAPABLE
