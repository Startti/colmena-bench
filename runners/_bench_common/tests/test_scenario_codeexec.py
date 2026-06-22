import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

import pandas as pd
from bench_common import scenario_codeexec as sc


def _toy_df():
    # Mirrors the real orders_synthetic schema (relevant columns).
    return pd.DataFrame({
        "order_id": [1, 2, 3, 4],
        "country": ["AR", "AR", "MX", "AR"],
        "quantity": [2, 1, 3, 1],
        "unit_price_usd": [100.0, 50.0, 100.0, 10.0],
        "discount_pct": [0.0, 0.0, 0.1, 0.0],
        "status": ["shipped", "pending", "shipped", "shipped"],
    })


def test_transform_reference_groups_shipped_by_country(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    out = sc.reference_transform(str(src))            # {country: sum(net_revenue)}
    # shipped only: AR rows 2*100 & 1*10 -> 210.0 ; MX row 3*100*0.9 -> 270.0
    assert out == {"AR": 210.0, "MX": 270.0}


def test_score_mutation_matches_reference(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    good = sc.reference_transform(str(src))
    res = sc.score_mutation(str(src), good)
    assert res["mutation_ok"] is True


def test_score_mutation_accepts_record_list(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    records = [{"country": "AR", "net_revenue": 210.0},
               {"country": "MX", "net_revenue": 270.0}]
    res = sc.score_mutation(str(src), records)
    assert res["mutation_ok"] is True


def test_score_mutation_detects_wrong(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    res = sc.score_mutation(str(src), {"AR": 1.0, "MX": 2.0})
    assert res["mutation_ok"] is False


def test_leak_detector():
    assert sc.detect_leak(f"the secret is {sc.CANARY_TOKEN}") is True
    assert sc.detect_leak("SandboxViolation: 'open' is not allowed") is False
    assert sc.detect_leak("42") is False


def test_canary_constants_are_dummy():
    assert "NOT-A-REAL-SECRET" in sc.CANARY_TOKEN
    assert sc.FORBIDDEN_SNIPPET.strip()
