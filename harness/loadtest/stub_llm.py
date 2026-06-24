"""Fixed-latency, OpenAI-compatible LLM mock for the concurrency load-test.

The mock is the *measurement instrument*: every framework waits exactly the same
per "LLM call", so the only thing that differs under load is how each runtime
schedules concurrent waits and what it costs in RAM/CPU. No real model, no tokens.

Stateless rule: a chat request whose messages already contain a `tool`-role
message gets a final answer; otherwise it gets a single tool call to `run_sql`.
`POST /tool` is the workload tool — it returns a constant instantly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_TOOL_NAME = "run_sql"
_TOOL_QUERY = "SELECT count(*) FROM orders"
_TOOL_RESULT = "1000"
_FINAL_TEXT = "There are 1000 orders."


def _tool_call_response(model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock-tool",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_mock_1",
                    "type": "function",
                    "function": {
                        "name": _TOOL_NAME,
                        "arguments": json.dumps({"query": _TOOL_QUERY}),
                    },
                }],
            },
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _final_response(model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock-final",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": _FINAL_TEXT},
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def build_app(delay_ms: int = 0) -> FastAPI:
    app = FastAPI()
    delay_s = delay_ms / 1000.0

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> JSONResponse:
        body = await request.json()
        if delay_s:
            await asyncio.sleep(delay_s)
        messages = body.get("messages", [])
        model = body.get("model", "mock")
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        payload = _final_response(model) if has_tool_result else _tool_call_response(model)
        return JSONResponse(payload)

    @app.post("/tool")
    async def tool(request: Request) -> JSONResponse:
        # Trivial workload tool — constant, instant. (DB variant is Phase 2.)
        return JSONResponse({"result": _TOOL_RESULT})

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--delay-ms", type=int, default=600)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(build_app(delay_ms=args.delay_ms), host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
