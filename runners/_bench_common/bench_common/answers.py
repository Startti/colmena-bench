"""Build the question block and extract a {question_id: answer} dict from text."""
from __future__ import annotations

import json
import re
from typing import Any


def build_questions_block(questions: dict) -> str:
    return "\n".join(f"{q['id']}: {q['text']}" for q in questions["questions"])


def extract_answer_dict(text: str) -> dict[str, Any]:
    if not text:
        return {}
    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text.strip())
    for c in candidates:
        try:
            val = json.loads(c)
            if isinstance(val, dict):
                return val
        except (json.JSONDecodeError, ValueError):
            continue
    return {}
