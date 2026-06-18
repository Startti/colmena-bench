import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from bench_common import scenario_refund as s  # noqa: E402


def test_assets_present_and_consistent():
    assert s.SECRET.startswith("sk-live-REFUND-")
    assert s.POLICY_MAX_USD == 100.0
    assert s.REQUEST["amount"] > s.POLICY_MAX_USD          # guarantees a first-draft violation
    assert "approve" in s.CANONICAL_HUMAN_ANSWER.lower()


def test_policy_check_is_deterministic():
    assert s.policy_violation({"decision": "approve", "amount": 250.0}) is True
    assert s.policy_violation({"decision": "partial", "amount": 100.0}) is False


def test_payment_tool_returns_structured_fields_with_isolated_secret():
    out = s.payment_lookup(order_id="ORD-1", api_key=s.SECRET)
    assert isinstance(out, dict)
    assert s.SECRET in out["auth_token"]          # secret isolated in its own field
    assert s.SECRET not in out["order_info"]      # reasoning field free of the secret
    assert "ORD-1" in out["order_info"]


def test_pass_fail_checks_shape():
    checks = s.evaluate(answer={"decision": "partial"}, retries=1, secret_leaked=False)
    assert set(checks) == {"hitl_ok", "critic_ok", "masking_ok", "all_ok"}
    assert checks["all_ok"] is True


def test_evaluate_fails_when_secret_leaked():
    checks = s.evaluate(answer={"decision": "partial"}, retries=1, secret_leaked=True)
    assert checks["masking_ok"] is False and checks["all_ok"] is False
