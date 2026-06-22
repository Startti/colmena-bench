"""Task 4 naive — CrewAI, CSV injected into the prompt."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, Task

from bench_common import (
    RunnerArgs, variant_params, read_csv_text, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    csv_text = read_csv_text(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}\n\nCSV DATA:\n{csv_text}"
    agent = Agent(role="data analyst", goal="answer questions from CSV",
                  backstory="Expert analyst.", llm=llm, allow_delegation=False, verbose=False)
    crew_task = Task(description=prompt, expected_output="A JSON object of answers.", agent=agent)
    crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)

    result = crew.kickoff()
    answer = extract_answer_dict(str(result))
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
