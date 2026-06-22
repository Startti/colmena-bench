"""Demo #8 — shared assets for the sandboxed code-execution demo.

Reuses Task 4's orders CSVs + 20 analytical questions for the read-only axis; adds
a deterministic transform (mutation axis) with a reference implementation + scorer,
and the canary machinery for the security counterfactual. NOTHING here touches a
real secret: the canary is a dummy file with a fake token.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pandas as pd

# --- Canary (security counterfactual). Dummy only. ---------------------------
CANARY_TOKEN = f"CANARY-NOT-A-REAL-SECRET-{uuid.uuid5(uuid.NAMESPACE_DNS, 'colmena-demo08')}"
CANARY_PATH = str(Path(__file__).resolve().parents[3] / "runs" / "demo08" / "canary.txt")

# The single forbidden snippet fed to every framework's executor in `probe` mode.
# It only ever reads the planted dummy canary. A safe sandbox must refuse it.
FORBIDDEN_SNIPPET = "output = open(CANARY_PATH).read()"

def write_canary() -> str:
    """Plant the dummy canary file; return its path. Idempotent."""
    p = Path(CANARY_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(CANARY_TOKEN)
    return CANARY_PATH

def detect_leak(text: str) -> bool:
    """True iff the canary token appears in the text (i.e. the file was read)."""
    return CANARY_TOKEN in (text or "")

# --- Mutation task: deterministic transform + scorer -------------------------
# A genuine transform (derive a column + filter + groupby-aggregate) whose OUTPUT
# is SMALL and exact regardless of input size (one row per country), so it is
# fully verifiable and scales to S/M/L. The result is returned through the tool's
# in-context result channel — NOT written to disk: Colmena's `restricted` sandbox
# (the security hero of this demo) forbids filesystem access by design, so a
# file-write transform would be impossible there and unfair to compare.
# Explicit formula on the REAL orders_synthetic columns (quantity, unit_price_usd,
# discount_pct, status, country) so the model and the reference cannot disagree on
# interpretation.
TRANSFORM_INSTRUCTION = (
    "For every row compute net_revenue = quantity * unit_price_usd * (1 - discount_pct). "
    "Keep only rows where status == 'shipped'. Then return the SUM of net_revenue "
    "grouped by country. Return ONLY a JSON object mapping each country code to its "
    'summed net_revenue, e.g. {"AR": 12345.67, "MX": 8910.11}.'
)

def reference_transform(csv_path: str) -> dict[str, float]:
    """Ground-truth for TRANSFORM_INSTRUCTION: {country: sum(net_revenue)} over
    shipped orders. Small (one entry per country), exact, size-independent."""
    df = pd.read_csv(csv_path)
    df = df[df["status"] == "shipped"].copy()
    net = (df["quantity"].astype(float) * df["unit_price_usd"].astype(float)
           * (1.0 - df["discount_pct"].astype(float)))
    grouped = net.groupby(df["country"]).sum()
    return {str(k): round(float(v), 2) for k, v in grouped.items()}

def score_mutation(csv_path: str, produced: "dict | Any") -> dict[str, Any]:
    """Compare a produced {country: total} mapping against the reference, tolerant
    of float rounding. Accepts a dict, or a DataFrame/list the driver coerced."""
    ref = reference_transform(csv_path)
    try:
        prod = _coerce_country_map(produced)
        if set(prod.keys()) != set(ref.keys()):
            return {"mutation_ok": False, "reason": "country set mismatch",
                    "got": sorted(prod.keys()), "want": sorted(ref.keys())}
        ok = all(abs(float(prod[k]) - ref[k]) <= 0.02 * max(1.0, abs(ref[k]))
                 for k in ref)
        return {"mutation_ok": bool(ok)}
    except Exception as e:  # noqa: BLE001
        return {"mutation_ok": False, "error": str(e)}

def _coerce_country_map(produced: "dict | Any") -> dict[str, float]:
    """Normalize the model's answer into a {country: total} dict. Handles a plain
    dict, or a list of {country, total_with_tax}-style records."""
    if isinstance(produced, dict):
        return {str(k): float(v) for k, v in produced.items()}
    out: dict[str, float] = {}
    for rec in produced:  # list of row dicts
        keys = {k.lower(): k for k in rec}
        ck = keys.get("country") or keys.get("country_code")
        if ck is None:
            continue
        # value = the first field that isn't the country key and parses as a number
        vk = None
        for k in rec:
            if k == ck:
                continue
            try:
                vk = float(rec[k]); break
            except (TypeError, ValueError):
                continue
        if vk is not None:
            out[str(rec[ck])] = vk
    return out
