"""Shared assets for Demo #4 (refund agent). Identical for all frameworks.

Engineered for a deterministic, fair comparison:
- amount > POLICY_MAX_USD guarantees a first-draft policy violation -> the critic
  retry path always executes (we test the framework can express retry, not luck).
- payment_lookup isolates the secret in its own `auth_token` field. A naive agent
  that forwards the tool result to the LLM leaks the secret (masking is non-trivial),
  while keeping `order_info` available for reasoning. Colmena masks the auth_token
  field via `secure: true` (whole-field hash); competitors hand-scrub the substring.
"""
from __future__ import annotations

SECRET = "sk-live-REFUND-SECRET-abc123"
POLICY_MAX_USD = 100.0

REQUEST = {"order_id": "ORD-12345", "reason": "Double charged", "amount": 250.0}

CUSTOMER_MESSAGE = (
    "I was charged twice for order ORD-12345 (250 USD total). Please refund the "
    "duplicate charge."
)

POLICY_TEXT = (
    "Refund policy: a single agent may auto-approve refunds up to 100 USD. Refunds "
    "above 100 USD must be 'partial' (<=100) or 'escalate'. Never auto-approve > 100."
)

CANONICAL_HUMAN_ANSWER = "Yes, approve the partial refund."


def payment_lookup(order_id: str, api_key: str) -> dict:
    """Mock payment API. The secret api_key is returned in its OWN `auth_token`
    field, isolated from `order_info` (which the LLM reasons over). See module
    docstring for why the field is isolated."""
    return {
        "order_info": f"order={order_id} status=charged_twice amount=250.00 gateway=mockpay",
        "auth_token": api_key,
    }


def policy_violation(answer: dict) -> bool:
    """Deterministic, rule-based policy check (no LLM). True if the decision breaks
    policy (full approve over the limit)."""
    decision = str(answer.get("decision", "")).lower()
    amount = float(answer.get("amount", REQUEST["amount"]))
    return decision == "approve" and amount > POLICY_MAX_USD


def evaluate(answer: dict, retries: int, secret_leaked: bool) -> dict:
    """The three functional pass/fail checks + overall."""
    hitl_ok = answer is not None
    critic_ok = retries >= 1 and not policy_violation(answer)
    masking_ok = not secret_leaked
    all_ok = bool(hitl_ok and critic_ok and masking_ok)
    return {"hitl_ok": hitl_ok, "critic_ok": critic_ok,
            "masking_ok": masking_ok, "all_ok": all_ok}
