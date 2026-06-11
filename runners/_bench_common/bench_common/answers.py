"""Build the question block and extract a {question_id: answer} dict from text."""
from __future__ import annotations

import json
import re
from typing import Any


def build_questions_block(questions: dict) -> str:
    return "\n".join(f"{q['id']}: {q['text']}" for q in questions["questions"])


_QID = re.compile(r"^Q\d+$")


def extract_answer_dict(text: str) -> dict[str, Any]:
    """Pull the answers dict from a model message.

    A message may contain several JSON objects (e.g. a tool-call payload like
    {"query": "..."} plus the final answers). We collect every parseable JSON
    object and pick the one that looks most like answers — most `Q\\d+` keys,
    then most keys overall. Falls back to {} if nothing parses.
    """
    if not text:
        return {}
    dicts: list[dict] = []
    # All fenced blocks (greedy per fence).
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        _try_load(m.group(1), dicts)
    # Every brace-balanced span in the text.
    for span in _balanced_spans(text):
        _try_load(span, dicts)
    # Whole string.
    _try_load(text.strip(), dicts)
    if not dicts:
        return {}

    def score(d: dict) -> tuple[int, int]:
        qkeys = sum(1 for k in d if _QID.match(str(k)))
        return (qkeys, len(d))

    return max(dicts, key=score)


def _try_load(s: str, out: list[dict]) -> None:
    try:
        v = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return
    if isinstance(v, dict):
        out.append(v)


def _balanced_spans(text: str) -> list[str]:
    """Return every top-level brace-balanced {...} substring."""
    spans, depth, start = [], 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    spans.append(text[start : i + 1])
    return spans
