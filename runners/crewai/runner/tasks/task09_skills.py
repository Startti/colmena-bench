"""Demo #9 — CrewAI handler: naive (prompt-stuff) arm of the Skills demo.

Stuffs the entire knowledge corpus into the system prompt (the naive strategy
Colmena's load_skill is designed to beat) and asks one question. Tokens are
measured by the driver from proxy spans; usage is returned as zeros.

CrewAI's idiomatic single LLM call is a one-agent, one-task Crew (mirror
task01/task08): the corpus goes into the agent's backstory (the system-prompt
slot) and the question into the task description. No tools. Only the `naive`
arm is implemented here; non-naive arms raise ValueError for now.
"""
from __future__ import annotations

import os
from typing import Any

from crewai import Agent, Crew, Task

from bench_common import RunnerArgs
from bench_common import scenario_skills as sk


def _ask_llm(llm: Any, system: str, user: str) -> str:
    # One-agent / one-task crew (mirror task01/task08). The corpus is the
    # agent backstory (system slot); the question is the task description.
    # `llm` is the proxy-wired crewai.LLM passed in by the driver.
    agent = Agent(
        role="finance analyst",
        goal="Apply the correct policy from the manual to answer the question.",
        backstory=system,
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
    crew_task = Task(
        description=user,
        expected_output="The answer to the question.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)
    result = crew.kickoff()
    return str(result)


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
