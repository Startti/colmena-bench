import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demo_tools_session_run as d


def test_configs():
    names = [c["name"] for c in d.CONFIGS]
    assert "colmena-lazy" in names and "colmena-eager" in names
    assert {"crewai", "langchain", "langgraph", "llamaindex", "google_adk"} <= set(names)


def test_colmena_lazy_flags():
    by_name = {c["name"]: c for c in d.CONFIGS}
    assert by_name["colmena-lazy"]["lazy"] == "1"
    assert by_name["colmena-eager"]["lazy"] == "0"


def test_defaults():
    assert list(d.SEEDS) == [0, 1, 2, 3, 4]
    assert d.N_TOOLS == 30 and d.N_TURNS == 10


def test_calls_by_turn_assigns_to_right_turn():
    # 3 turns: boundaries at epoch 100, 110, 120, 130.
    boundaries = [100.0, 110.0, 120.0, 130.0]
    calls = [
        {"tool": "a", "ts": 105.0},   # turn 0
        {"tool": "b", "ts": 110.0},   # turn 1 (left-inclusive next edge)
        {"tool": "c", "ts": 119.9},   # turn 1
        {"tool": "d", "ts": 125.0},   # turn 2
        {"tool": "e", "ts": 200.0},   # after last edge -> last turn (2)
    ]
    buckets = d.calls_by_turn(calls, boundaries)
    assert len(buckets) == 3
    assert [c["tool"] for c in buckets[0]] == ["a"]
    assert [c["tool"] for c in buckets[1]] == ["b", "c"]
    assert [c["tool"] for c in buckets[2]] == ["d", "e"]


def test_calls_by_turn_iso_boundaries():
    boundaries = ["2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z", "2026-01-01T00:00:20Z"]
    from orchestrator.demo05_buckets import _to_epoch
    e0 = _to_epoch(boundaries[0])
    calls = [{"tool": "x", "ts": e0 + 1}, {"tool": "y", "ts": e0 + 11}]
    buckets = d.calls_by_turn(calls, boundaries)
    assert [c["tool"] for c in buckets[0]] == ["x"]
    assert [c["tool"] for c in buckets[1]] == ["y"]


def test_load_spans_from_offset(tmp_path):
    f = tmp_path / "run-demo07.jsonl"
    f.write_text('{"tokens_input": 10}\n{"tokens_input": 20}\n{"tokens_input": 30}\n')
    spans = d.load_spans_from_offset(f, 1)
    assert [s["tokens_input"] for s in spans] == [20, 30]


def test_aggregate_means_over_seeds():
    records = [
        {"config": "colmena-lazy", "hard_error": False, "turns": [
            {"turn": 0, "per_turn_tokens": 100, "cum_tokens": 100,
             "selection_ok": True, "arg_ok": True, "wrong_tool_called": False}]},
        {"config": "colmena-lazy", "hard_error": False, "turns": [
            {"turn": 0, "per_turn_tokens": 200, "cum_tokens": 200,
             "selection_ok": False, "arg_ok": True, "wrong_tool_called": False}]},
    ]
    rows = d._aggregate(records)
    assert len(rows) == 1
    assert rows[0]["cum_tokens_mean"] == 150
    assert rows[0]["selection_acc"] == 0.5
    assert rows[0]["seeds"] == 2
