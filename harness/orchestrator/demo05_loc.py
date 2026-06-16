"""Lines-of-code counter for the node-vs-code metric (Hero Demo #1).

Counts non-blank, non-comment-only lines. For .py, a line whose first
non-whitespace char is '#' is a comment. For .json (Colmena DAG), every
non-blank line counts.
"""
from __future__ import annotations

from pathlib import Path


def count_loc(path: Path) -> int:
    text = Path(path).read_text()
    is_py = str(path).endswith(".py")
    n = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if is_py and line.startswith("#"):
            continue
        n += 1
    return n
