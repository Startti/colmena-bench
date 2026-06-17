"""Task 4 naive — LangGraph, CSV injected into the prompt.

Single-node StateGraph that calls the model once, so the measured overhead
reflects LangGraph's graph machinery (not just a bare model call).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from bench_common import (
    RunnerArgs, variant_params, read_csv_text, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


class State(TypedDict):
    messages: Annotated[list, add_messages]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    csv_text = read_csv_text(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}\n\nCSV DATA:\n{csv_text}"

    def call_model(state: State):
        return {"messages": [llm.invoke(state["messages"])]}

    graph = StateGraph(State)
    graph.add_node("model", call_model)
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    app = graph.compile()

    result = app.invoke({"messages": [("user", prompt)]})
    final = result["messages"][-1]
    text = final.content if hasattr(final, "content") else str(final)
    answer = extract_answer_dict(str(text))

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    meta = getattr(final, "usage_metadata", None)
    if meta:
        usage["input"] = int(meta.get("input_tokens", 0) or 0)
        usage["output"] = int(meta.get("output_tokens", 0) or 0)
        details = meta.get("input_token_details") or {}
        usage["cached"] = int(details.get("cache_read", 0) or 0)
    return answer, usage
