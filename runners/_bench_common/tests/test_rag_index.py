import sys
from pathlib import Path
PKG = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(PKG))
from bench_common import scenario_skills as sk
from bench_common import rag_index as ri


def test_chunk_corpus_yields_pack_tagged_chunks(tmp_path):
    sk.materialize_corpus(str(tmp_path), 5, seed=0)
    chunks = ri.chunk_corpus(str(tmp_path))
    assert all({"pack", "relpath", "text"} <= set(c) for c in chunks)
    assert any(c["pack"] == "tax-by-region" for c in chunks)
    # sentinel excluded
    assert all(not c["relpath"].endswith(".colmena_corpus") for c in chunks)


def test_correct_chunk_hit_matches_flat_leaf(tmp_path):
    q = next(q for q in sk.QUESTION_BANK if q.id == "tax_br")   # leaf_path rates/latam
    assert ri.correct_chunk_hit(q, [{"pack": "tax-by-region", "relpath": "references/latam.md"}]) is True
    assert ri.correct_chunk_hit(q, [{"pack": "tax-by-region", "relpath": "references/eu.md"}]) is False
    assert ri.correct_chunk_hit(q, [{"pack": "returns-and-refunds", "relpath": "references/latam.md"}]) is False
