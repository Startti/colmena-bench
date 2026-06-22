"""Demo #9 — LangGraph handler: naive (prompt-stuff) arm of the Skills demo.

Stuffs the entire knowledge corpus into the system prompt (the naive strategy
Colmena's load_skill is designed to beat) and asks one question. Tokens are
measured by the driver from proxy spans; usage is returned as zeros.

For a single completion there is no graph to build — LangGraph wraps a
LangChain ChatOpenAI model, so a plain `.invoke` with system+user is the
faithful naive call (mirror task01/task08 wiring). Only the `naive` arm is
implemented here; non-naive arms raise ValueError for now.
"""
from __future__ import annotations

import os
from typing import Any

from bench_common import RunnerArgs
from bench_common import scenario_skills as sk


def _ask_llm(llm: Any, system: str, user: str) -> str:
    # Plain system+user invoke through the proxy-wired ChatOpenAI client
    # (the `llm` arg is already pointed at the proxy, same as LangChain).
    resp = llm.invoke([("system", system), ("user", user)])
    return resp.content if hasattr(resp, "content") else str(resp)


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    arm = os.environ.get("BENCH_SKILLS_ARM", "naive")
    skills_dir = os.environ["BENCH_SKILLS_DIR"]
    qid = os.environ["BENCH_QUESTION_ID"]
    question = next(q for q in sk.QUESTION_BANK if q.id == qid)

    if arm != "naive":
        raise ValueError(f"arm {arm!r} not supported")

    system = sk.build_naive_system_prompt(skills_dir)
    answer = _ask_llm(llm, system, question.text)

    usage = {"input": 0, "output": 0, "cached": 0}
    extras = {"arm": arm, "question_id": qid}
    return str(answer), usage, extras
