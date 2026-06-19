import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demo_tools_run as d


def test_configs():
    names = [c["name"] for c in d.CONFIGS]
    assert "colmena-lazy" in names and "colmena-eager" in names
    assert {"crewai", "langchain", "langgraph", "llamaindex", "google_adk"} <= set(names)


def test_default_grid():
    assert d.DEFAULT_COUNTS == [5, 10, 25, 50, 100, 200]
    assert d.DEFAULT_DIFFICULTIES == ["easy", "medium", "hard"]
    assert d.DEFAULT_TRIALS == 5


def test_sum_tokens_delta(tmp_path):
    f = tmp_path / "run-demo07.jsonl"
    f.write_text('{"tokens_input": 10}\n{"tokens_input": 20}\n')
    assert d.sum_tokens_from_offset(f, 0) == 30
    assert d.sum_tokens_from_offset(f, 1) == 20   # only new lines after offset
    assert d.line_count(f) == 2
