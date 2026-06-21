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
TRANSFORM_INSTRUCTION = (
    "Add a column `total_with_tax` = amount * 1.08, then keep only rows where "
    "status == 'shipped'. Return the resulting table."
)

def reference_transform(csv_path: str) -> pd.DataFrame:
    """Ground-truth implementation of TRANSFORM_INSTRUCTION."""
    df = pd.read_csv(csv_path)
    df = df.copy()
    df["total_with_tax"] = df["amount"].astype(float) * 1.08
    df = df[df["status"] == "shipped"].reset_index(drop=True)
    return df

def score_mutation(csv_path: str, produced: pd.DataFrame) -> dict[str, Any]:
    """Compare a produced DataFrame against the reference on shape/cols/values."""
    ref = reference_transform(csv_path)
    try:
        p = produced.reset_index(drop=True)
        same_cols = set(p.columns) == set(ref.columns)
        same_shape = p.shape == ref.shape
        ok = bool(same_cols and same_shape)
        if ok:
            p = p[list(ref.columns)]
            for c in ref.columns:
                if pd.api.types.is_numeric_dtype(ref[c]):
                    ok = ok and bool((abs(p[c].astype(float) - ref[c].astype(float)) < 1e-6).all())
                else:
                    ok = ok and bool((p[c].astype(str).values == ref[c].astype(str).values).all())
        return {"mutation_ok": ok, "same_cols": same_cols, "same_shape": same_shape}
    except Exception as e:  # noqa: BLE001
        return {"mutation_ok": False, "error": str(e)}
