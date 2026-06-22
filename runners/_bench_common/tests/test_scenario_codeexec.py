import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

import pandas as pd
from bench_common import scenario_codeexec as sc


def _toy_df():
    return pd.DataFrame({
        "order_id": [1, 2, 3, 4],
        "amount": [100.0, 50.0, 200.0, 10.0],
        "status": ["shipped", "pending", "shipped", "shipped"],
        "country": ["AR", "AR", "MX", "AR"],
    })


def test_transform_reference_groups_shipped_by_country(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    out = sc.reference_transform(str(src))            # {country: sum(total_with_tax)}
    # shipped only: AR rows 100 & 10 -> (100+10)*1.08 = 118.8 ; MX row 200 -> 216.0
    assert out == {"AR": 118.8, "MX": 216.0}


def test_score_mutation_matches_reference(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    good = sc.reference_transform(str(src))
    res = sc.score_mutation(str(src), good)
    assert res["mutation_ok"] is True


def test_score_mutation_accepts_record_list(tmp_path):
    src = tmp_path / "in.csv"; _toy_df().to_csv(src, index=False)
    records = [{"country": "AR", "total_with_tax": 118.8},
               {"country": "MX", "total_with_tax": 216.0}]
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
