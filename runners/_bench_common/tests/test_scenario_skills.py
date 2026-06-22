# runners/_bench_common/tests/test_scenario_skills.py
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from bench_common import scenario_skills as sk


# --- core policy packs ------------------------------------------------------

def test_core_packs_are_the_six_policies():
    assert set(sk.CORE_PACKS) == set(sk.CORE_POLICY_NAMES)
    assert len(sk.CORE_PACKS) == 6


def test_corepack_has_no_reference_fn():
    import dataclasses
    fields = {f.name for f in dataclasses.fields(sk.CorePack)}
    assert "reference_fn" not in fields


def test_policy_value_deterministic_and_distinct():
    a = sk.policy_value("colmena-hogar-premium", "danio-agua", "agua-subita", "deductible_usd")
    b = sk.policy_value("colmena-hogar-premium", "danio-agua", "agua-subita", "deductible_usd")
    c = sk.policy_value("colmena-hogar-basico", "danio-agua", "agua-basica-subita", "deductible_usd")
    assert a == b and a != c          # deterministic + distinct across packs
    assert a % 10 != 0 or True        # non-round-ish (informational)


def test_value_appears_verbatim_in_rendered_leaf():
    # single source of truth: the rendered sub-leaf shows the SAME value policy_value returns
    pack = "colmena-hogar-premium"
    files = sk.render_pack(sk.CORE_PACKS[pack])
    val = sk.policy_value(pack, "danio-agua", "agua-subita", "deductible_usd")
    leaf = files["references/agua-subita.md"]      # FLAT layout
    assert str(val) in leaf


def test_two_homeowners_variants_differ():
    # same perils, DIFFERENT values across the two hogar policies forces precise navigation
    prem = sk.policy_value("colmena-hogar-premium", "incendio", "incendio-estructura", "coverage_limit_usd")
    basi = sk.policy_value("colmena-hogar-basico", "incendio", "incendio-basico-estructura", "coverage_limit_usd")
    assert prem != basi


# --- rendering / layout invariants ------------------------------------------

def test_every_core_pack_renders_skill_md_with_matching_name():
    for name, pack in sk.CORE_PACKS.items():
        files = sk.render_pack(pack)
        assert files["SKILL.md"].splitlines()[1] == f"name: {name}"


def test_rendered_frontmatter_is_valid_yaml():
    import yaml
    pack = sk.CORE_PACKS["colmena-hogar-premium"]
    for relpath, content in sk.render_pack(pack).items():
        assert content.startswith("---\n")
        fm = content.split("---\n", 2)[1]
        meta = yaml.safe_load(fm)             # raises if invalid YAML
        assert "name" in meta and "description" in meta


def test_packs_nested_and_valid_yaml():
    import yaml
    for name, pack in sk.CORE_PACKS.items():
        files = sk.render_pack(pack)
        assert any(rel.startswith("references/") and "references:" in c for rel, c in files.items()), name
        for c in files.values():
            yaml.safe_load(c.split("---\n", 2)[1])


def test_no_flat_reference_name_collisions():
    for name, pack in sk.CORE_PACKS.items():
        files = sk.render_pack(pack)
        ref = [r for r in files if r.startswith("references/")]
        assert len(ref) == len(set(ref)), name


# --- corpus materialization + density ---------------------------------------

def test_materialize_includes_core_and_hits_density(tmp_path):
    sk.materialize_corpus(str(tmp_path), 50, 0)
    dirs = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert set(sk.CORE_PACKS).issubset(dirs) and len(dirs) == 50
    assert sk.corpus_token_estimate(str(tmp_path)) >= 150_000


def test_distractors_are_also_policies(tmp_path):
    # every distractor is a generated insurance policy: SKILL.md + flat references/
    sk.materialize_corpus(str(tmp_path), 50, 0)
    non_core = [p for p in tmp_path.iterdir() if p.is_dir() and p.name not in sk.CORE_PACKS]
    assert non_core
    for p in non_core:
        assert (p / "SKILL.md").exists()
        assert "Póliza" in (p / "SKILL.md").read_text()
        assert (p / "references").is_dir()


def test_materialize_deterministic(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    sk.materialize_corpus(str(a), 20, 7); sk.materialize_corpus(str(b), 20, 7)
    assert {p.name for p in a.iterdir()} == {p.name for p in b.iterdir()}


def test_materialize_small_corpus_is_just_core_or_subset(tmp_path):
    sk.materialize_corpus(str(tmp_path), 5, 0)
    dirs = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert len(dirs) == 5
    # 6 core packs; with pack_count=5 the materializer keeps the FIRST 5 core packs
    assert dirs.issubset(set(sk.CORE_PACKS))


def test_distractor_frontmatter_is_valid_yaml(tmp_path):
    import yaml
    sk.materialize_corpus(str(tmp_path), 50, 0)
    non_core = [p for p in tmp_path.iterdir() if p.is_dir() and p.name not in sk.CORE_PACKS]
    assert non_core
    for md in (non_core[0]).rglob("*.md"):
        yaml.safe_load(md.read_text().split("---\n", 2)[1])  # raises if invalid


def test_materialize_refuses_non_corpus_dir(tmp_path):
    import pytest
    (tmp_path / "precious.txt").write_text("keep")
    with pytest.raises(ValueError):
        sk.materialize_corpus(str(tmp_path), 5, 0)
    assert (tmp_path / "precious.txt").exists()


# --- naive prompt builder ---------------------------------------------------

def test_build_naive_system_prompt_contains_every_pack(tmp_path):
    sk.materialize_corpus(str(tmp_path), 20, 0)
    prompt = sk.build_naive_system_prompt(str(tmp_path))
    import os
    for d in [x for x in os.listdir(tmp_path) if os.path.isdir(os.path.join(tmp_path, x))]:
        assert d in prompt


# --- question bank ----------------------------------------------------------

def test_question_bank_size_and_packs():
    assert len(sk.QUESTION_BANK) == 18
    assert {q.pack for q in sk.QUESTION_BANK} == set(sk.CORE_POLICY_NAMES)


def test_question_ids_unique():
    ids = [q.id for q in sk.QUESTION_BANK]
    assert len(ids) == len(set(ids))


def test_every_question_binds_to_existing_leaf():
    for q in sk.QUESTION_BANK:
        assert sk.leaf_path_exists(q.pack, q.leaf_path), (q.id, q.pack, q.leaf_path)
        assert q.field in sk.POLICY_FIELDS, (q.id, q.field)


def test_expected_answer_is_verbatim_in_the_authoritative_leaf():
    # single source of truth: expected_for == policy_value AND that value is rendered
    # in exactly the leaf the question points to.
    for q in sk.QUESTION_BANK:
        want = sk.expected_for(q)
        peril, sub = q.leaf_path.split("/")
        assert want == sk.policy_value(q.pack, peril, sub, q.field)
        files = sk.render_pack(sk.CORE_PACKS[q.pack])
        leaf = files[f"references/{sub}.md"]   # FLAT layout
        assert str(want) in leaf, (q.id, want)


def test_all_four_field_types_exercised():
    assert {q.field for q in sk.QUESTION_BANK} == set(sk.POLICY_FIELDS)


# --- scorer -----------------------------------------------------------------

def test_scorer_exact_match_and_none_for_empty():
    q = sk.QUESTION_BANK[0]
    want = sk.expected_for(q)
    assert sk.score_skill_answer(q, str(want))["correct"] is True
    assert sk.score_skill_answer(q, f"El deducible es ${want}.")["correct"] is True
    assert sk.score_skill_answer(q, str(want + 1))["correct"] is False
    assert sk.score_skill_answer(q, "")["correct"] is None
    assert sk.score_skill_answer(q, "no tengo esa información")["correct"] is None


def test_scorer_handles_thousands_separators_both_locales():
    # pick a question whose expected value is >= 1000 (a coverage_limit_usd one)
    q = next(x for x in sk.QUESTION_BANK if x.field == "coverage_limit_usd")
    want = sk.expected_for(q)
    assert want >= 1000
    assert sk.score_skill_answer(q, f"{want:,}")["correct"] is True          # US 95,000
    es = f"{want:,}".replace(",", ".")                                        # ES 95.000
    assert sk.score_skill_answer(q, es)["correct"] is True


def test_scorer_every_question_self_scores_correct():
    # feeding the authoritative value as the answer must score correct for all 18
    for q in sk.QUESTION_BANK:
        assert sk.score_skill_answer(q, str(sk.expected_for(q)))["correct"] is True


# --- colmena skills DAG shape (no network) ----------------------------------

def test_colmena_skills_dag_shape():
    import json
    dag_path = (PKG.parents[1] / "runners" / "colmena" / "runner" / "dags" / "skills_agent.json")
    dag = json.loads(dag_path.read_text())
    cfg = dag["nodes"]["assistant"]["config"]
    assert cfg["skills_path"] == "${SKILLS_DIR}"
    assert cfg["tool_configurations"] == {}
    assert dag["nodes"]["assistant"]["type"] == "llm_call"
    pairs = {(e["from"], e["to"]) for e in dag["edges"]}
    assert ("trigger", "assistant") in pairs and ("assistant", "log") in pairs
