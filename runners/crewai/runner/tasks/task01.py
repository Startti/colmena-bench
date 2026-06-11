"""Task 1 — hello world.

A single-agent crew that does one LLM call. Touchstone for "framework
overhead". We intentionally use the minimal idiomatic CrewAI construction
(Agent + Task + Crew) so the LOC and overhead numbers reflect what a real
user would write.
"""
from __future__ import annotations

from typing import Any

from crewai import Agent, Crew, Task

from bench_common import RunnerArgs


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    agent = Agent(
        role="responder",
        goal="Respond with the word hello.",
        backstory="A minimal baseline agent.",
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )
    crew_task = Task(
        description=task_def["prompt"],
        expected_output="A single word.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)

    result = crew.kickoff()
    answer = str(result)

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    # CrewAI exposes per-run token usage on the result in 1.x. We read it
    # if available; the proxy spans file is the canonical source.
    usage_data = getattr(result, "token_usage", None) or getattr(result, "usage", None)
    if usage_data is not None:
        usage["input"] = int(getattr(usage_data, "prompt_tokens", 0) or 0)
        usage["output"] = int(getattr(usage_data, "completion_tokens", 0) or 0)
        usage["cached"] = int(getattr(usage_data, "cached_prompt_tokens", 0) or 0)
    return answer, usage
