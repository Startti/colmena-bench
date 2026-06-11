import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
from bench_common import variant_params  # noqa: E402


def test_variant_params_returns_matching_entry():
    task = {"variants": [{"name": "S", "dataset_path": "seeds/S.csv"},
                          {"name": "M", "dataset_path": "seeds/M.csv"}]}
    assert variant_params(task, "M") == {"name": "M", "dataset_path": "seeds/M.csv"}


def test_variant_params_missing_returns_empty():
    assert variant_params({"variants": [{"name": "S"}]}, "L") == {}
    assert variant_params({}, "S") == {}
