# runners/_bench_common/tests/test_scenario_skills.py
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

import pandas as pd
from bench_common import scenario_skills as sk


def _toy_df():
    # shipped DE: 2*100 and 1*50 = 250 gross; shipped FR: 3*100 = 300 gross
    return pd.DataFrame({
        "country":       ["DE", "DE", "FR", "DE"],
        "quantity":      [2, 1, 3, 5],
        "unit_price_usd":[100.0, 50.0, 100.0, 10.0],
        "status":        ["shipped", "shipped", "shipped", "pending"],
    })


def test_tax_pack_reference_fn_excludes_vat_with_pack_rate():
    pack = sk.CORE_PACKS["tax-by-region"]
    # DE VAT rate from the pack facts; ex-VAT net = gross / (1+rate)
    got = pack.reference_fn(_toy_df(), {"country": "DE", "status": "shipped"})
    rate = sk.TAX_RATES["DE"]
    want = round((2*100 + 1*50) / (1 + rate), 2)
    assert got == want


def test_tax_pack_no_drift_rendered_table_matches_facts():
    # The DE rate that appears in the rendered eu.md leaf MUST equal the fact
    # the reference_fn uses — single source of truth, cannot diverge.
    pack = sk.CORE_PACKS["tax-by-region"]
    files = sk.render_pack(pack)            # {relpath: content}
    eu_md = files["references/rates/eu.md"]
    assert "| DE | 19% |" in eu_md                    # DE row shows exactly 19%
    assert sk.TAX_RATES["DE"] == 0.19


def test_tax_pack_reference_tree_is_nested():
    pack = sk.CORE_PACKS["tax-by-region"]
    files = sk.render_pack(pack)
    # nested 3-level structure: SKILL.md -> references/rates.md -> references/rates/eu.md
    assert "references/rates.md" in files
    assert "references/rates/eu.md" in files
    assert "references/rates/latam.md" in files
    assert "references/rates/apac.md" in files
    assert "references/edge-cases/b2b.md" in files
    # the parent `rates` frontmatter must DECLARE its children (so load_skill can navigate)
    assert "name: eu" in files["references/rates.md"]


def test_rendered_frontmatter_is_valid_yaml():
    import yaml
    pack = sk.CORE_PACKS["tax-by-region"]
    for relpath, content in sk.render_pack(pack).items():
        assert content.startswith("---\n")
        fm = content.split("---\n", 2)[1]
        meta = yaml.safe_load(fm)             # raises if invalid YAML
        assert "name" in meta and "description" in meta
