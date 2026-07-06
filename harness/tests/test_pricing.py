"""Sanity-check the pricing table snapshot.

Not a unit-priced thing: this just enforces format + cross-validation alias
parity with `proxy/litellm_config.yaml`. Real cost numbers are verified
against the provider page at every official benchmark run (METHODOLOGY §1).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
PRICING_PATH = HARNESS_DIR / "pricing_table.json"
PROXY_CONFIG_PATH = REPO_ROOT / "proxy" / "litellm_config.yaml"

EXPECTED_ALIASES = {"gemini-2.5-flash", "claude-haiku", "gpt-4o-mini"}


def test_pricing_table_loads():
    data = json.loads(PRICING_PATH.read_text())
    assert data["version"]
    assert data["snapshot_date"]
    assert data["currency"] == "USD"
    assert data["unit"] == "per_million_tokens"


def test_all_cross_validation_aliases_priced():
    data = json.loads(PRICING_PATH.read_text())
    assert set(data["models"].keys()) == EXPECTED_ALIASES


def test_each_model_has_required_fields():
    data = json.loads(PRICING_PATH.read_text())
    for alias, entry in data["models"].items():
        assert "provider" in entry, alias
        assert "input_per_1m" in entry, alias
        assert "output_per_1m" in entry, alias
        assert entry["input_per_1m"] > 0, alias
        assert entry["output_per_1m"] > 0, alias
        assert entry["output_per_1m"] >= entry["input_per_1m"], (
            f"{alias}: output should not be cheaper than input"
        )


def _is_embedding(entry: dict) -> bool:
    """Embedding models are served by the proxy (for the demo09 RAG arm) but are
    intentionally absent from the pricing table, which prices chat input/output
    tokens only (`test_each_model_has_required_fields` even requires
    output_per_1m > 0, which embeddings have no analog for)."""
    name = entry.get("model_name", "")
    underlying = (entry.get("litellm_params") or {}).get("model", "")
    return "embedding" in name or "embedding" in underlying


def test_aliases_match_proxy_config():
    pricing = json.loads(PRICING_PATH.read_text())
    proxy = yaml.safe_load(PROXY_CONFIG_PATH.read_text())
    # Compare CHAT aliases only — embedding models are priced separately (not at all
    # here), so exclude them; a new chat alias in the proxy without a price, or a
    # priced alias missing from the proxy, still fails (real drift detection).
    proxy_aliases = {m["model_name"] for m in proxy["model_list"] if not _is_embedding(m)}
    pricing_aliases = set(pricing["models"].keys())
    assert proxy_aliases == pricing_aliases, (
        f"chat alias drift between pricing and proxy: only in proxy={proxy_aliases - pricing_aliases}, "
        f"only in pricing={pricing_aliases - proxy_aliases}"
    )


def test_sources_documented():
    data = json.loads(PRICING_PATH.read_text())
    for alias in data["models"]:
        assert alias in data["sources"], f"missing source URL for {alias}"
        assert data["sources"][alias].startswith("http")
