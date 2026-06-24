"""LangGraph warm server for the concurrency load-test.

Production-style deployment: one long-running uvicorn process with a pre-built
agent and a warm httpx client. The single tool `run_sql` POSTs to the mock's
/tool endpoint, matching the Colmena graph's http_request tool so the work is
identical across frameworks.
"""
from __future__ import annotations

import argparse
import os

import httpx
from fastapi import FastAPI
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, create_model

_MOCK_BASE = os.environ.get("LOADTEST_MOCK_BASE", "http://127.0.0.1:9100")
_MODEL = os.environ.get("LOADTEST_MODEL", "gemini-2.5-flash")
_SYSTEM = ("Answer the user's question. Use the run_sql tool exactly once, "
           "then report the count.")


class RunRequest(BaseModel):
    prompt: str = "How many orders are there?"


def build_app() -> FastAPI:
    app = FastAPI()
    # warm, shared client reused across requests
    client = httpx.Client(base_url=_MOCK_BASE, timeout=30.0)

    def _run_sql(query: str) -> str:
        return client.post("/tool", json={"query": query}).json()["result"]

    args_model = create_model("run_sql_Args", query=(str, ...))
    tool = StructuredTool.from_function(
        func=_run_sql, name="run_sql",
        description="Run a SQL query and return rows.", args_schema=args_model)

    llm = ChatOpenAI(
        model=_MODEL, base_url=f"{_MOCK_BASE}/v1", api_key="sk-loadtest-mock",
        temperature=0.0)
    agent = create_react_agent(llm, [tool])

    @app.post("/run")
    def run(req: RunRequest) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        out = agent.invoke({"messages": [SystemMessage(_SYSTEM), HumanMessage(req.prompt)]})
        last = out["messages"][-1]
        return {"answer": getattr(last, "content", str(last))}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9001)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
