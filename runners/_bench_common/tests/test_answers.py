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


def test_prefers_answers_over_toolcall_json():
    # A tool-call payload appears first; the real answers dict appears later.
    text = (
        'Calling tool {"query": "SELECT COUNT(*) FROM orders"}\n'
        'Final answer:\n{"Q01": 500, "Q02": 494, "Q03": 9999.0}'
    )
    out = extract_answer_dict(text)
    assert out == {"Q01": 500, "Q02": 494, "Q03": 9999.0}


def test_picks_dict_with_most_question_keys():
    text = '{"a": 1} and {"Q01": 1, "Q02": 2}'
    assert extract_answer_dict(text) == {"Q01": 1, "Q02": 2}


def test_build_questions_block_lists_all_20():
    qs = _json.loads((REPO / "data/orders_synthetic/questions_20.json").read_text())
    block = build_questions_block(qs)
    for q in qs["questions"]:
        assert q["id"] in block
        assert q["text"] in block
