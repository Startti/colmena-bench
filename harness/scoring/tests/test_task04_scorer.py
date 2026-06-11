import json
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HARNESS))
REPO = HARNESS.parent

from scoring.task04_scorer import score_answers  # noqa: E402

QUESTIONS = json.loads((REPO / "data/orders_synthetic/questions_20.json").read_text())
GT = json.loads((REPO / "data/orders_synthetic/ground_truth.json").read_text())
GT_S = GT["by_size"]["S"]["answers"]


def test_all_correct_scores_one():
    res = score_answers(GT_S, GT_S, QUESTIONS)
    assert res["success_rate"] == 1.0
    assert res["correct"] == 20


def test_string_form_numbers_pass():
    answers = dict(GT_S)
    answers["Q01"] = "500"
    answers["Q14"] = "$1,124,383.23"
    res = score_answers(answers, GT_S, QUESTIONS)
    assert res["per_question"]["Q01"] is True
    assert res["per_question"]["Q14"] is True


def test_float_within_tolerance():
    answers = dict(GT_S)
    answers["Q14"] = GT_S["Q14"] * 1.005
    assert score_answers(answers, GT_S, QUESTIONS)["per_question"]["Q14"] is True
    answers["Q14"] = GT_S["Q14"] * 1.05
    assert score_answers(answers, GT_S, QUESTIONS)["per_question"]["Q14"] is False


def test_missing_answer_is_wrong():
    answers = dict(GT_S)
    del answers["Q20"]
    res = score_answers(answers, GT_S, QUESTIONS)
    assert res["per_question"]["Q20"] is False
    assert res["correct"] == 19


def test_object_partial_keys_fail():
    answers = dict(GT_S)
    obj = dict(GT_S["Q06"])
    first_key = next(iter(obj))
    obj[first_key] = obj[first_key] * 2
    answers["Q06"] = obj
    assert score_answers(answers, GT_S, QUESTIONS)["per_question"]["Q06"] is False
