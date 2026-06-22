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


# --- Task 4: corpus materialization + density floor -------------------------

def test_materialize_corpus_always_includes_core_packs(tmp_path):
    sk.materialize_corpus(str(tmp_path), pack_count=50, seed=0)
    dirs = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert set(sk.CORE_PACKS).issubset(dirs)
    assert len(dirs) == 50
    assert (tmp_path / "tax-by-region" / "references" / "rates" / "eu.md").exists()


def test_corpus_is_information_dense_enough(tmp_path):
    sk.materialize_corpus(str(tmp_path), pack_count=50, seed=0)
    assert sk.corpus_token_estimate(str(tmp_path)) >= 150_000


def test_materialize_is_deterministic(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    sk.materialize_corpus(str(a), 20, seed=7)
    sk.materialize_corpus(str(b), 20, seed=7)
    assert {p.name for p in a.iterdir()} == {p.name for p in b.iterdir()}


def test_materialize_small_corpus_is_just_core_or_subset(tmp_path):
    sk.materialize_corpus(str(tmp_path), pack_count=5, seed=0)
    dirs = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert len(dirs) == 5
    # all 5 must be core packs (no distractors needed when pack_count<=len(core))... but
    # we have 6 core packs; with pack_count=5 the materializer keeps the FIRST 5 core packs.
    assert dirs.issubset(set(sk.CORE_PACKS))


def test_distractor_frontmatter_is_valid_yaml(tmp_path):
    import yaml
    sk.materialize_corpus(str(tmp_path), pack_count=50, seed=0)
    non_core = [p for p in tmp_path.iterdir() if p.is_dir() and p.name not in sk.CORE_PACKS]
    assert non_core
    for md in (non_core[0]).rglob("*.md"):
        yaml.safe_load(md.read_text().split("---\n",2)[1])  # raises if invalid


def test_materialize_refuses_non_corpus_dir(tmp_path):
    import pytest
    (tmp_path / "precious.txt").write_text("do not delete")
    with pytest.raises(ValueError):
        sk.materialize_corpus(str(tmp_path), 5, seed=0)
    assert (tmp_path / "precious.txt").exists()   # untouched


# --- Task 5: scorer + naive prompt builder ----------------------------------

def test_score_skill_answer_tolerant_and_none_for_empty():
    q = sk.QUESTION_BANK[0]
    df = pd.read_csv(PKG.parents[1] / "data" / "orders_synthetic" / "seeds" / "M.csv")
    truth = sk.CORE_PACKS[q.pack].reference_fn(df, q.params)
    assert sk.score_skill_answer(q, str(truth), df)["correct"] is True
    assert sk.score_skill_answer(q, f"{truth*1.10:.2f}", df)["correct"] is False
    assert sk.score_skill_answer(q, "", df)["correct"] is None     # not measured
    assert sk.score_skill_answer(q, "no idea", df)["correct"] is None

def test_parse_number_handles_scientific_and_signs():
    # access the private helper directly
    assert sk._parse_number("1.2e5") == 120000.0
    assert sk._parse_number("-$1,234.56") == -1234.56
    assert sk._parse_number("$0.50") == 0.5
    assert sk._parse_number("no number here") is None
    assert sk._parse_number("") is None
    assert sk._parse_number(None) is None

def test_score_skill_answer_parses_currency_and_commas():
    q = sk.QUESTION_BANK[0]
    df = pd.read_csv(PKG.parents[1] / "data" / "orders_synthetic" / "seeds" / "M.csv")
    truth = sk.CORE_PACKS[q.pack].reference_fn(df, q.params)
    # answer wrapped in prose + thousands separators + $ should still parse
    assert sk.score_skill_answer(q, f"The answer is ${truth:,.2f} total.", df)["correct"] is True

def test_build_naive_system_prompt_contains_every_pack(tmp_path):
    sk.materialize_corpus(str(tmp_path), 20, seed=0)
    prompt = sk.build_naive_system_prompt(str(tmp_path))
    assert "tax-by-region" in prompt
    # every pack dir name should appear somewhere in the concatenation
    import os
    for d in [x for x in os.listdir(tmp_path) if os.path.isdir(os.path.join(tmp_path, x))]:
        assert d in prompt


# --- Task 6: colmena skills DAG shape (no network) --------------------------

def test_colmena_skills_dag_shape():
    import json
    dag_path = (PKG.parents[1] / "runners" / "colmena" / "runner" / "dags" / "skills_agent.json")
    dag = json.loads(dag_path.read_text())
    cfg = dag["nodes"]["assistant"]["config"]
    assert cfg["skills_path"] == "${SKILLS_DIR}"
    assert cfg["tool_configurations"] == {}
    assert dag["nodes"]["assistant"]["type"] == "llm_call"
    # edges: trigger->assistant->log
    pairs = {(e["from"], e["to"]) for e in dag["edges"]}
    assert ("trigger", "assistant") in pairs and ("assistant", "log") in pairs
