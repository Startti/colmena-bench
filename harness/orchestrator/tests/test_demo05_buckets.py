from datetime import datetime, timezone

from demo05_buckets import bucket_spans_by_turn, _to_epoch


def _iso(sec: int) -> str:
    return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def test_buckets_spans_into_turns_and_cumulates():
    boundaries = [_iso(0), _iso(10), _iso(20), _iso(30)]
    spans = [
        {"ts_start": _to_epoch(_iso(1)), "tokens_input": 100, "tokens_output": 5},
        {"ts_start": _to_epoch(_iso(2)), "tokens_input": 50, "tokens_output": 5},
        {"ts_start": _to_epoch(_iso(12)), "tokens_input": 200, "tokens_output": 9},
        {"ts_start": _to_epoch(_iso(25)), "tokens_input": 400, "tokens_output": 9},
    ]
    res = bucket_spans_by_turn(spans, boundaries)
    assert res["per_turn_input"] == [150, 200, 400]
    assert res["cumulative_input"] == [150, 350, 750]
    assert res["per_turn_output"] == [10, 9, 9]


def test_spans_after_last_boundary_go_to_last_turn():
    boundaries = [_iso(0), _iso(10)]
    spans = [{"ts_start": _to_epoch(_iso(99)), "tokens_input": 7, "tokens_output": 1}]
    res = bucket_spans_by_turn(spans, boundaries)
    assert res["per_turn_input"] == [7]
