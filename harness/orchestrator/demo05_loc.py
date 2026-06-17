"""Lines-of-code counter for the node-vs-code metric (Hero Demo #1).

Counts non-blank, non-comment-only lines. For .py, a line whose first
non-whitespace char is '#' is a comment, and docstrings (module-, class-,
and function-level) are excluded so long documentation does not inflate the
code count. For .json (Colmena DAG), every non-blank line counts.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _docstring_lines(text: str) -> set[int]:
    """Return the set of physical (1-based) line numbers occupied by
    module-, class-, and function-level docstrings.

    A docstring is an ``ast.Expr`` whose value is a string ``ast.Constant``
    appearing as the FIRST statement of a Module / FunctionDef /
    AsyncFunctionDef / ClassDef body. Returns an empty set if parsing fails.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()

    lines: set[int] = set()
    holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            start = first.lineno
            end = getattr(first, "end_lineno", start) or start
            lines.update(range(start, end + 1))
    return lines


def count_loc(path: Path) -> int:
    text = Path(path).read_text()
    is_py = str(path).endswith(".py")
    skip_lines = _docstring_lines(text) if is_py else set()
    n = 0
    for idx, raw in enumerate(text.splitlines(), start=1):
        if idx in skip_lines:
            continue
        line = raw.strip()
        if not line:
            continue
        if is_py and line.startswith("#"):
            continue
        n += 1
    return n
