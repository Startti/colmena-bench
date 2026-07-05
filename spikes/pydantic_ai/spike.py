"""Feasibility spike: Pydantic AI -> LiteLLM proxy -> gemini-2.5-flash.

Proves the three make-or-break requirements for adding this framework as a
benchmark runner:
  1. point the model client at the proxy's OpenAI-compatible base_url + master key
  2. inject the `x-bench-run-id` request header so the proxy buckets spans per run
  3. drive a multi-turn conversation with a tool call

Success = the proxy writes proxy/spans/run-<SPIKE_RUN_ID>.jsonl with token usage.
"""
import asyncio
import os
import sys

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

RUN_ID = os.environ.get("SPIKE_RUN_ID", "spike-pydantic")
BASE = os.environ.get("LITELLM_PROXY_BASE_URL", "http://127.0.0.1:4000").rstrip("/")
KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-1234")

# (1) base_url + master key, and (2) the x-bench-run-id header on every request.
client = AsyncOpenAI(
    base_url=f"{BASE}/v1",
    api_key=KEY,
    default_headers={"x-bench-run-id": RUN_ID},
)
model = OpenAIChatModel("gemini-2.5-flash", provider=OpenAIProvider(openai_client=client))
agent = Agent(model, system_prompt="You are a helpful assistant. Use tools when relevant.")


@agent.tool_plain
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


def _out(res):
    return getattr(res, "output", None) or getattr(res, "data", None) or str(res)


async def main() -> int:
    # (3a) turn 1 — should trigger the add tool
    r1 = await agent.run("What is 21 plus 21? Use the add tool.")
    print("TURN1:", _out(r1))
    # (3b) turn 2 — multi-turn via message history
    r2 = await agent.run("Now add 100 to that result.", message_history=r1.all_messages())
    print("TURN2:", _out(r2))
    print("OK pydantic_ai spike completed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
