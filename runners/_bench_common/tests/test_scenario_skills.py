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


def test_all_core_packs_present():
    assert set(sk.CORE_PACKS) == {
        "tax-by-region", "returns-and-refunds", "revenue-recognition",
        "discount-and-promo", "payment-method-fees", "shipping-cost-allocation",
    }


def test_revenue_recognition_applies_category_fee():
    df = pd.DataFrame({
        "product_category": ["electronics", "electronics", "apparel"],
        "quantity": [1, 2, 1], "unit_price_usd": [100.0, 100.0, 50.0],
        "status": ["shipped", "shipped", "shipped"],
    })
    got = sk.CORE_PACKS["revenue-recognition"].reference_fn(df, {"category": "electronics"})
    want = round((100 + 200) * (1 - 0.08), 2)
    assert got == want


def test_discount_cap_applied():
    df = pd.DataFrame({
        "channel": ["web", "web"], "quantity": [1, 1],
        "unit_price_usd": [100.0, 100.0], "discount_pct": [0.5, 0.1],
        "status": ["shipped", "shipped"],
    })
    got = sk.CORE_PACKS["discount-and-promo"].reference_fn(df, {"channel": "web"})
    assert got == round(70 + 90, 2)   # web cap 0.30: 0.5->0.3 -> 70; 0.1 -> 90


def test_every_core_pack_renders_skill_md_with_matching_name():
    for name, pack in sk.CORE_PACKS.items():
        files = sk.render_pack(pack)
        assert files["SKILL.md"].splitlines()[1] == f"name: {name}"


def test_all_core_packs_nested_and_valid_yaml():
    import yaml
    for name, pack in sk.CORE_PACKS.items():
        files = sk.render_pack(pack)
        # at least one 3-level nested leaf: references/<parent>/<child>.md
        assert any("/" in rel.split("references/",1)[1] for rel in files if rel.startswith("references/")), name
        for content in files.values():
            yaml.safe_load(content.split("---\n",2)[1])   # raises if invalid


def test_core_pack_reference_fns_run_on_real_dataset():
    df = pd.read_csv(PKG.parents[1] / "data" / "orders_synthetic" / "seeds" / "M.csv")
    checks = {
        "returns-and-refunds": {"channel": df["channel"].iloc[0]},
        "revenue-recognition": {"category": df["product_category"].iloc[0]},
        "discount-and-promo": {"channel": df["channel"].iloc[0]},
        "payment-method-fees": {"payment_method": df["payment_method"].iloc[0]},
        "shipping-cost-allocation": {"country": df["country"].iloc[0]},
    }
    for pack_name, params in checks.items():
        val = sk.CORE_PACKS[pack_name].reference_fn(df, params)
        assert isinstance(val, float)


# --- Task 3: question bank --------------------------------------------------

def test_question_bank_size_and_packs():
    assert len(sk.QUESTION_BANK) >= 18
    assert {q.pack for q in sk.QUESTION_BANK} == set(sk.CORE_PACKS)


def test_question_ids_unique():
    ids = [q.id for q in sk.QUESTION_BANK]
    assert len(ids) == len(set(ids))


def test_every_question_binds_to_an_existing_leaf_and_runs():
    df = pd.read_csv(PKG.parents[1] / "data" / "orders_synthetic" / "seeds" / "M.csv")
    for q in sk.QUESTION_BANK:
        assert sk.leaf_path_exists(q.pack, q.leaf_path), (q.id, q.pack, q.leaf_path)
        val = sk.CORE_PACKS[q.pack].reference_fn(df, q.params)
        assert isinstance(val, float)


def test_every_question_has_a_nonzero_or_defined_answer():
    df = pd.read_csv(PKG.parents[1] / "data" / "orders_synthetic" / "seeds" / "M.csv")
    assert len(df[df["status"] == "shipped"]) > 0
    for q in sk.QUESTION_BANK:
        val = sk.CORE_PACKS[q.pack].reference_fn(df, q.params)
        assert val != 0.0, (q.id, "selects empty/zero frame — pick params present in M.csv shipped rows")
