# runners/_bench_common/tests/test_scenario_tools.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_common import scenario_tools as st  # noqa: E402


def test_count_and_needle():
    spec = st.generate_toolset(10, seed=1)
    assert spec["n_tools"] == 10 and len(spec["tools"]) == 10
    assert sum(t["is_needle"] for t in spec["tools"]) == 1
    assert next(t for t in spec["tools"] if t["is_needle"])["name"] == spec["needle"]


def test_question_does_not_name_the_tool():
    for s in range(8):
        spec = st.generate_toolset(10, seed=s)
        assert spec["needle"] not in spec["question"]   # intent must not name the tool


def test_needle_cluster_confusers_present():
    spec = st.generate_toolset(5, seed=2)
    # at n=5 the toolset is the needle's full cluster: all 5 tools share the cluster
    names = {t["name"] for t in spec["tools"]}
    assert spec["needle"] in names and len(names) == 5
    # and they are all in the needle's cluster
    assert all(t["cluster"] == spec["cluster"] for t in spec["tools"])


def test_needle_has_required_args_in_question():
    spec = st.generate_toolset(10, seed=3)
    assert spec["expected_args"]
    for k, v in spec["expected_args"].items():
        assert str(v) in spec["question"]   # the value is stated in the intent


def test_deterministic():
    assert st.generate_toolset(20, seed=4) == st.generate_toolset(20, seed=4)


def test_trials_vary_needle_or_cluster():
    clusters = {st.generate_toolset(10, seed=s)["cluster"] for s in range(8)}
    assert len(clusters) > 1   # different scenarios across seeds


def test_realistic_descriptions():
    spec = st.generate_toolset(10, seed=1)
    for t in spec["tools"]:
        assert 20 <= len(t["description"]) <= 400
        assert 10 <= len(t["summary"]) <= 200
        assert all(p.get("description") for p in t["params"])  # every param has a real description


def test_needle_required_args_match_expected():
    # every required param on the needle is represented in expected_args
    for s in range(8):
        spec = st.generate_toolset(10, seed=s)
        needle = next(t for t in spec["tools"] if t["is_needle"])
        required = {p["name"] for p in needle["params"] if p["required"]}
        assert set(spec["expected_args"]) == required
        assert 2 <= len(required) <= 4


def test_score_right_tool():
    spec = st.generate_toolset(10, seed=1)
    log = [{"tool": spec["needle"], "args": spec["expected_args"]}]
    r = st.score(spec, log, f"done: {spec['expected_answer']}")
    assert r["selection_ok"] and r["arg_ok"] and r["answer_ok"] and not r["wrong_tool_called"]


def test_score_confuser_flagged():
    spec = st.generate_toolset(10, seed=1)
    # call a DIFFERENT tool from the SAME cluster (a genuine cluster-mate)
    confuser = next(
        t["name"] for t in spec["tools"]
        if not t["is_needle"] and t["cluster"] == spec["cluster"]
    )
    r = st.score(spec, [{"tool": confuser, "args": {}}], "not applicable")
    assert r["selection_ok"] is False
    assert r["wrong_tool_called"] is True
    assert r["arg_ok"] is False
    assert r["answer_ok"] is False


def test_score_unrelated_tool_not_flagged_as_confuser():
    # an out-of-cluster tool is wrong selection but NOT a cluster-confusion signal
    spec = st.generate_toolset(20, seed=6)
    other = next(
        (t["name"] for t in spec["tools"] if t["cluster"] != spec["cluster"]),
        None,
    )
    assert other is not None
    r = st.score(spec, [{"tool": other, "args": {}}], "not applicable")
    assert r["selection_ok"] is False
    assert r["wrong_tool_called"] is False


def test_session_shape():
    s = st.generate_session(30, 10, seed=0)
    assert s["n_turns"] == 10 and len(s["turns"]) == 10
    assert abs(len(s["tools"]) - 30) <= 2
    names = {t["name"] for t in s["tools"]}
    for turn in s["turns"]:
        assert turn["needle"] in names          # every turn's needle is in the fixed set
        assert turn["needle"] not in turn["question"]   # intent does not name the tool


def test_session_deterministic():
    assert st.generate_session(30, 10, seed=1) == st.generate_session(30, 10, seed=1)


def test_session_turns_vary():
    s = st.generate_session(30, 10, seed=2)
    clusters = {t["cluster"] for t in s["turns"]}
    assert len(clusters) >= 3      # turns span several clusters


def test_score_turn_right():
    s = st.generate_session(30, 10, seed=0)
    t0 = s["turns"][0]
    r = st.score_turn(s, 0, [{"tool": t0["needle"], "args": t0["expected_args"]}], f"ok {t0['expected_answer']}")
    assert r["selection_ok"] and r["arg_ok"] and r["answer_ok"]


def test_log_and_read_round_trip(tmp_path, monkeypatch):
    p = tmp_path / "tc.jsonl"
    monkeypatch.setenv("BENCH_TOOLCALL_LOG", str(p))
    st.log_tool_call("create_refund", {"order_id": "A-1042"})
    st.log_tool_call("create_refund", {"order_id": "A-1043"})
    calls = st.read_tool_calls(p)
    assert [{"tool": c["tool"], "args": c["args"]} for c in calls] == [
        {"tool": "create_refund", "args": {"order_id": "A-1042"}},
        {"tool": "create_refund", "args": {"order_id": "A-1043"}},
    ]


def test_log_tool_call_has_ts(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_TOOLCALL_LOG", str(tmp_path / "tc.jsonl"))
    st.log_tool_call("x", {"a": 1})
    rec = st.read_tool_calls(tmp_path / "tc.jsonl")[0]
    assert rec["tool"] == "x" and "ts" in rec
