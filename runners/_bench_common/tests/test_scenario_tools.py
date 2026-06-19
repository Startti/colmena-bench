# runners/_bench_common/tests/test_scenario_tools.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_common import scenario_tools as st  # noqa: E402

def test_count_and_needle_present():
    spec = st.generate_toolset(50, "hard", seed=3)
    assert spec["n_tools"] == 50
    assert len(spec["tools"]) == 50
    needles = [t for t in spec["tools"] if t["is_needle"]]
    assert len(needles) == 1
    assert needles[0]["name"] == spec["needle"]

def test_difficulty_param_counts():
    easy = st.generate_toolset(20, "easy", seed=1)
    hard = st.generate_toolset(20, "hard", seed=1)
    en = next(t for t in easy["tools"] if t["is_needle"])
    hn = next(t for t in hard["tools"] if t["is_needle"])
    assert 1 <= len(en["params"]) <= 2
    assert 6 <= len(hn["params"]) <= 10

def test_population_is_mixed_difficulty():
    spec = st.generate_toolset(60, "medium", seed=2)
    sizes = [len(t["params"]) for t in spec["tools"] if not t["is_needle"]]
    assert min(sizes) <= 2 and max(sizes) >= 6

def test_summaries_distinguishable_at_200():
    spec = st.generate_toolset(200, "hard", seed=7)
    names = [t["name"] for t in spec["tools"]]
    summaries = [t["summary"] for t in spec["tools"]]
    assert len(set(names)) == 200
    assert len(set(summaries)) == 200
    for s in summaries:
        assert 10 <= len(s) <= 200

def test_question_and_expected_args():
    spec = st.generate_toolset(10, "hard", seed=5)
    needle = next(t for t in spec["tools"] if t["is_needle"])
    for p in needle["params"]:
        if p["required"]:
            assert p["name"] in spec["expected_args"]
            assert str(spec["expected_args"][p["name"]]) in spec["question"]

def test_needle_random_position_varies_with_seed():
    idx = lambda s: next(i for i, t in enumerate(st.generate_toolset(50, "easy", seed=s)["tools"]) if t["is_needle"])
    assert len({idx(s) for s in range(8)}) > 1

def test_deterministic_for_same_seed():
    a = st.generate_toolset(30, "medium", seed=4)
    b = st.generate_toolset(30, "medium", seed=4)
    assert a == b

def test_score_all_correct():
    spec = st.generate_toolset(10, "easy", seed=1)
    log = [{"tool": spec["needle"], "args": spec["expected_args"]}]
    res = st.score(spec, log, final_answer=f"The answer is {spec['expected_answer']}.")
    assert res == {"selection_ok": True, "arg_ok": True, "answer_ok": True}

def test_score_wrong_tool():
    spec = st.generate_toolset(10, "easy", seed=1)
    res = st.score(spec, [{"tool": "some_distractor", "args": {}}], final_answer="not applicable")
    assert res["selection_ok"] is False and res["answer_ok"] is False

def test_log_and_read_round_trip(tmp_path, monkeypatch):
    p = tmp_path / "tc.jsonl"
    monkeypatch.setenv("BENCH_TOOLCALL_LOG", str(p))
    st.log_tool_call("get_order", {"id": "X7"})
    st.log_tool_call("get_order", {"id": "X8"})
    calls = st.read_tool_calls(p)
    assert calls == [{"tool": "get_order", "args": {"id": "X7"}}, {"tool": "get_order", "args": {"id": "X8"}}]
