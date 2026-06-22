"""Score Task 4's 20 answers against ground truth. Framework-agnostic.

The runner never sees ground truth; the orchestrator calls score_answers()
after a run completes. Comparison rules per questions_20.json answer_type:
integer exact, float within 1% relative, date string-equal, object/dict
key-by-key (numeric or string), object_top_n top-N keys, array ordered.
"""
from __future__ import annotations

import re
from typing import Any

FLOAT_REL_TOL = 0.01


def _to_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = re.sub(r"[,$%\s]", "", v.strip())
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _num_eq(a: Any, b: Any, *, is_int: bool) -> bool:
    na, nb = _to_number(a), _to_number(b)
    if na is None or nb is None:
        return False
    if is_int:
        return round(na) == round(nb)
    if nb == 0:
        return abs(na) < 1e-9
    return abs(na - nb) / abs(nb) <= FLOAT_REL_TOL


def _str_eq(a: Any, b: Any) -> bool:
    return str(a).strip() == str(b).strip()


def _value_eq(a: Any, b: Any) -> bool:
    """Generic value compare: numbers by float tol, else string."""
    if _to_number(b) is not None:
        return _num_eq(a, b, is_int=isinstance(b, int))
    return _str_eq(a, b)


def _score_one(answer: Any, truth: Any, atype: str, top_n: int | None) -> bool:
    if answer is None:
        return False
    if atype == "integer":
        return _num_eq(answer, truth, is_int=True)
    if atype == "float":
        return _num_eq(answer, truth, is_int=False)
    if atype == "date":
        return _str_eq(answer, truth)
    if atype in ("object", "object_top_n"):
        if not isinstance(answer, dict) or not isinstance(truth, dict):
            return False
        keys = list(truth.keys())
        if atype == "object_top_n" and top_n:
            keys = keys[:top_n]
        for k in keys:
            if k not in answer or not _value_eq(answer[k], truth[k]):
                return False
        return True
    if atype == "array":
        if not isinstance(answer, list):
            return False
        truth_list = truth if isinstance(truth, list) else list(truth)
        if len(answer) != len(truth_list):
            return False
        return all(_str_eq(a, b) for a, b in zip(answer, truth_list))
    return _str_eq(answer, truth)


def score_answers(answers: dict, truth: dict, questions: dict) -> dict:
    per_question: dict[str, bool] = {}
    for q in questions["questions"]:
        qid = q["id"]
        ok = _score_one(answers.get(qid), truth.get(qid), q["answer_type"], q.get("top_n"))
        per_question[qid] = bool(ok)
    correct = sum(1 for v in per_question.values() if v)
    total = len(questions["questions"])
    return {
        "per_question": per_question,
        "correct": correct,
        "total": total,
        "success_rate": correct / total if total else 0.0,
    }
