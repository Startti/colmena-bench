"""Demo #9 — LlamaIndex handler: naive (prompt-stuff) arm of the Skills demo.

Stuffs the entire knowledge corpus into the system prompt (the naive strategy
Colmena's load_skill is designed to beat) and asks one question. Tokens are
measured by the driver from proxy spans; usage is returned as zeros.

Only the `naive` arm is implemented here. The RAG arm (BENCH_SKILLS_ARM=rag)
is added in a later task; non-naive arms raise ValueError for now.
"""
from __future__ import annotations

import os
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole

from bench_common import RunnerArgs
from bench_common import scenario_skills as sk


def _ask_llm(llm: Any, system: str, user: str) -> str:
    # Plain system+user chat through the proxy-wired OpenAILike client (mirror
    # task01/task08 wiring — the `llm` arg is already pointed at the proxy).
    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=system),
        ChatMessage(role=MessageRole.USER, content=user),
    ]
    resp = llm.chat(messages)
    return resp.message.content if hasattr(resp, "message") else str(resp)


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
