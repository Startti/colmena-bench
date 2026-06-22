import sys
from pathlib import Path
PKG = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(PKG))
from bench_common import scenario_skills as sk
from bench_common import rag_index as ri


def test_chunk_corpus_yields_pack_tagged_chunks(tmp_path):
    sk.materialize_corpus(str(tmp_path), 5, seed=0)
    chunks = ri.chunk_corpus(str(tmp_path))
    assert all({"pack", "relpath", "text"} <= set(c) for c in chunks)
    assert any(c["pack"] == "colmena-hogar-premium" for c in chunks)
    # sentinel excluded
    assert all(not c["relpath"].endswith(".colmena_corpus") for c in chunks)


def test_correct_chunk_hit_matches_flat_leaf():
    # Pull a real question from the restored QUESTION_BANK. Its leaf_path's last
    # segment maps to the FLAT on-disk file references/<segment>.md.
    q = next(x for x in sk.QUESTION_BANK if x.id == "hogar_prem_agua_subita_ded")
    leaf = q.leaf_path.split("/")[-1]          # "agua-subita"
    assert ri.correct_chunk_hit(q, [{"pack": q.pack, "relpath": f"references/{leaf}.md"}]) is True
    assert ri.correct_chunk_hit(q, [{"pack": q.pack, "relpath": "references/agua-gradual.md"}]) is False
    assert ri.correct_chunk_hit(q, [{"pack": "colmena-hogar-basico", "relpath": f"references/{leaf}.md"}]) is False
