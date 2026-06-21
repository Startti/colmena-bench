import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

import pandas as pd
from bench_common import scenario_codeexec as sc


def _toy_df():
    return pd.DataFrame({
        "order_id": [1, 2, 3],
        "amount": [100.0, 50.0, 200.0],
        "status": ["shipped", "pending", "shipped"],
    })

def test_transform_reference_adds_tax_and_filters(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    out = sc.reference_transform(str(src))            # returns a DataFrame
    assert "total_with_tax" in out.columns
    assert (out["status"] == "shipped").all()         # only shipped kept
    assert out["total_with_tax"].tolist() == [108.0, 216.0]

def test_score_mutation_matches_reference(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    good = sc.reference_transform(str(src))
    res = sc.score_mutation(str(src), good)
    assert res["mutation_ok"] is True

def test_score_mutation_detects_wrong(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    bad = _toy_df()                                    # untransformed
    res = sc.score_mutation(str(src), bad)
    assert res["mutation_ok"] is False

def test_leak_detector():
    assert sc.detect_leak(f"the secret is {sc.CANARY_TOKEN}") is True
    assert sc.detect_leak("SandboxViolation: 'open' is not allowed") is False
    assert sc.detect_leak("42") is False

def test_canary_constants_are_dummy():
    assert "NOT-A-REAL-SECRET" in sc.CANARY_TOKEN
    assert sc.FORBIDDEN_SNIPPET.strip()               # non-empty
