"""Demo #10 — secure_suspend scenario assets. All secrets are FAKE.

The 3 secrets share a per-import MARKER substring, so auditing the MARKER in the
proxy catches ANY of them leaking into an LLM prompt (the proxy audit takes one
needle). Delivery is verified by the mock recording the real values.
"""
from __future__ import annotations
import json, uuid
from pathlib import Path

MARKER = f"D10MARK-{uuid.uuid5(uuid.NAMESPACE_DNS, 'colmena-demo10')}"  # stable, fake

ONBOARDING_PROMPT = (
    "Connect the user's account to the payments provider. You do NOT have the "
    "credentials — you must ask the user for them, then call the connect endpoint. "
    "Collect the API key, API secret, and webhook signing secret, then connect."
)

def secrets() -> dict[str, str]:
    return {
        "api_key": f"ak-{MARKER}",
        "api_secret": f"as-{MARKER}",
        "webhook_signing_secret": f"wh-{MARKER}",
    }

def resume_payload() -> str:
    """One Q/A resume answering all 3 secret ids in a single round-trip."""
    s = secrets()
    return "\n".join(f"Q[{n}]: provide {n}\nA[{n}]: {v}" for n, v in s.items())

def read_leaked(mask_path: str):
    """True/False from the proxy mask-<run_id>.json; None if the file is absent,
    unreadable, or missing the secret_leaked key (unknown != clean)."""
    p = Path(mask_path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    val = data.get("secret_leaked")
    if val is None:
        return None
    return bool(val)

def delivered_to_api(received_path: str) -> bool:
    """True iff the mock received ALL three REAL secret values (not handles)."""
    p = Path(received_path)
    if not p.exists():
        return False
    blob = p.read_text()
    return all(v in blob for v in secrets().values())

def echo_leaked_from_text(text: str) -> bool:
    """True iff a real secret value appears in an LLM-visible text (echo path)."""
    return any(v in (text or "") for v in secrets().values())
