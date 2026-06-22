"""Task 1 — hello world, on LangGraph.

Builds a minimal single-node StateGraph that calls the model, so the
measured overhead reflects LangGraph's graph machinery (not just a bare
model call).
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated, TypedDict

from bench_common import RunnerArgs


class State(TypedDict):
    messages: Annotated[list, add_messages]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    def call_model(state: State):
        return {"messages": [llm.invoke(state["messages"])]}

    graph = StateGraph(State)
    graph.add_node("model", call_model)
    graph.add_edge(START, "model")
    graph.add_edge("model", END)
    app = graph.compile()

    result = app.invoke({"messages": [("user", task_def["prompt"])]})
    final = result["messages"][-1]
    answer = final.content if hasattr(final, "content") else str(final)

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    meta = getattr(final, "usage_metadata", None)
    if meta:
        usage["input"] = int(meta.get("input_tokens", 0) or 0)
        usage["output"] = int(meta.get("output_tokens", 0) or 0)
        details = meta.get("input_token_details") or {}
        usage["cached"] = int(details.get("cache_read", 0) or 0)
    return answer, usage
