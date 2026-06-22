"""Task 4 expert — CrewAI, run_sql tool over SQLite (CSV not in context)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, Task
from crewai.tools import tool

from bench_common import (
    RunnerArgs, variant_params, load_orders_sqlite, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    conn, run_sql = load_orders_sqlite(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    @tool("run_sql")
    def run_sql_tool(query: str) -> str:
        """Run a read-only SQL SELECT against the `orders` table and return rows as text."""
        return run_sql(query)

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}"
    agent = Agent(role="data analyst", goal="answer questions via SQL",
                  backstory="Expert SQL analyst.", llm=llm, tools=[run_sql_tool],
                  allow_delegation=False, verbose=False)
    crew_task = Task(description=prompt, expected_output="A JSON object of answers.", agent=agent)
    crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)

    try:
        result = crew.kickoff()
        answer = extract_answer_dict(str(result))
    finally:
        conn.close()
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
