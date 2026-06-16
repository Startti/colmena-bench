import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from bench_common import core


def _args(tmp_path: Path) -> core.RunnerArgs:
    task = tmp_path / "t.yaml"
    task.write_text('id: "demo"\nsuccess:\n  kind: regex\n  pattern: "."\n')
    return core.RunnerArgs(
        task=task, variant="default", run_id="r1", model_alias="gemini-2.5-flash",
        proxy_base_url="http://x", output=tmp_path / "o.json", timeout_seconds=10,
    )


def test_run_threads_handler_extras_into_output(tmp_path, monkeypatch):
    args = _args(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "runner", "--task", str(args.task), "--variant", "default",
        "--run-id", "r1", "--model-alias", "gemini-2.5-flash",
        "--proxy-base-url", "http://x", "--output", str(args.output),
        "--timeout-seconds", "10",
    ])

    def handler(task, llm, a):
        return "ok", {"input": 1, "output": 1, "cached": 0, "tool_calls": 0}, {"turn_boundaries": ["t0", "t1"]}

    core.run("fw", lambda: "1.0", lambda a: None, {"demo": handler})
    out = json.loads(args.output.read_text())
    assert out["extras"]["turn_boundaries"] == ["t0", "t1"]


def test_run_still_accepts_two_tuple(tmp_path, monkeypatch):
    args = _args(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "runner", "--task", str(args.task), "--variant", "default",
        "--run-id", "r1", "--model-alias", "gemini-2.5-flash",
        "--proxy-base-url", "http://x", "--output", str(args.output),
        "--timeout-seconds", "10",
    ])

    def handler(task, llm, a):
        return "ok", {"input": 1, "output": 1, "cached": 0, "tool_calls": 0}

    core.run("fw", lambda: "1.0", lambda a: None, {"demo": handler})
    out = json.loads(args.output.read_text())
    assert out["answer"] == "ok"
    assert out["extras"] == {}
