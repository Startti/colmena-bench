import json as _json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
REPO = PKG.parent.parent

from bench_common.answers import extract_answer_dict, build_questions_block  # noqa: E402


def test_plain_json():
    assert extract_answer_dict('{"Q01": 500, "Q02": 494}') == {"Q01": 500, "Q02": 494}


def test_json_in_code_fence():
    text = "Here are the answers:\n```json\n{\"Q01\": 500}\n```\nDone."
    assert extract_answer_dict(text) == {"Q01": 500}


def test_json_embedded_in_prose():
    text = 'The result is {"Q01": 500, "Q14": 1124383.23} based on the data.'
    assert extract_answer_dict(text) == {"Q01": 500, "Q14": 1124383.23}


def test_no_json_returns_empty():
    assert extract_answer_dict("I could not answer.") == {}


def test_build_questions_block_lists_all_20():
    qs = _json.loads((REPO / "data/orders_synthetic/questions_20.json").read_text())
    block = build_questions_block(qs)
    for q in qs["questions"]:
        assert q["id"] in block
        assert q["text"] in block
