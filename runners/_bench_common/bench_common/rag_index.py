"""Demo #9 — shared RAG helpers (framework-agnostic): chunk a corpus dir and
detect whether retrieval surfaced the leaf a question needs."""
from __future__ import annotations
from pathlib import Path


def chunk_corpus(corpus_dir: str) -> list[dict]:
    """One chunk per .md file (each pack file is already leaf-sized < 64KB). Each
    chunk is tagged with its pack (top dir) and relpath so retrieval hits can be
    scored. Skips the .colmena_corpus sentinel (not a .md)."""
    root = Path(corpus_dir)
    out: list[dict] = []
    for md in sorted(root.rglob("*.md")):
        rel = md.relative_to(root)
        out.append({
            "pack": rel.parts[0],
            "relpath": str(Path(*rel.parts[1:])),
            "text": md.read_text(),
        })
    return out


def correct_chunk_hit(question, retrieved: list[dict]) -> bool:
    """True iff a retrieved chunk is the question's pack AND its needed leaf
    (references/<leaf_path-last-segment>.md). Reference files are stored FLAT, so
    the on-disk relpath for logical leaf_path 'rates/eu' is 'references/eu.md'."""
    leaf_name = question.leaf_path.split("/")[-1]
    want_rel = f"references/{leaf_name}.md"
    return any(
        r.get("pack") == question.pack and r.get("relpath") == want_rel
        for r in retrieved
    )
