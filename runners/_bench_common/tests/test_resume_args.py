from pathlib import Path
from bench_common.core import parse_args

def test_resume_args_parse():
    a = parse_args("x", ["--task", "t.yaml", "--variant", "default", "--run-id", "r",
                         "--model-alias", "gemini-2.5-flash", "--proxy-base-url", "u",
                         "--output", "o.json", "--resume-state", "s.json",
                         "--resume-answer", "A[approve_refund]: yes"])
    assert a.resume_state == Path("s.json")
    assert a.resume_answer == "A[approve_refund]: yes"

def test_resume_args_default_none():
    a = parse_args("x", ["--task", "t.yaml", "--variant", "default", "--run-id", "r",
                         "--model-alias", "gemini-2.5-flash", "--proxy-base-url", "u",
                         "--output", "o.json"])
    assert a.resume_state is None and a.resume_answer is None
