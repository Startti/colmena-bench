import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
REPO = PKG.parent.parent

from bench_common import scenario05 as s  # noqa: E402


def test_report_is_substantial_text():
    assert isinstance(s.REPORT_TEXT, str)
    assert len(s.REPORT_TEXT) >= 12_000


def test_turn_script_is_ten_typed_turns():
    assert len(s.TURNS) == 10
    types = {t["type"] for t in s.TURNS}
    assert types == {"doc", "chart", "follow_up"}
    assert sum(t["type"] == "doc" for t in s.TURNS) == 4
    assert sum(t["type"] == "chart" for t in s.TURNS) == 3
    assert sum(t["type"] == "follow_up" for t in s.TURNS) == 3
    for t in s.TURNS:
        assert t["message"].strip()


def test_generate_chart_returns_fixed_data_uri():
    a = s.generate_chart("bar chart of revenue")
    b = s.generate_chart("completely different request")
    assert a == b
    assert a.startswith("data:image/png;base64,")
    assert len(a) >= 15_000


def test_report_filename_and_doc_id():
    assert s.REPORT_DOC_ID and isinstance(s.REPORT_DOC_ID, str)
    assert s.REPORT_FILENAME.endswith((".md", ".txt"))
