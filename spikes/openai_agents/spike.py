"""Feasibility spike: OpenAI Agents SDK -> LiteLLM proxy -> gemini-2.5-flash.

Proves:
  1. base_url + master key via a custom AsyncOpenAI client (Chat Completions, not Responses)
  2. x-bench-run-id header on every request -> per-run proxy spans
  3. multi-turn conversation with a tool call

Success = proxy/spans/run-<SPIKE_RUN_ID>.jsonl written with token usage.
"""
import asyncio
import os
import sys

from openai import AsyncOpenAI
from agents import (
    Agent,
    Runner,
    function_tool,
    set_default_openai_client,
    set_default_openai_api,
    set_tracing_disabled,
)

RUN_ID = os.environ.get("SPIKE_RUN_ID", "spike-openai-agents")
BASE = os.environ.get("LITELLM_PROXY_BASE_URL", "http://127.0.0.1:4000").rstrip("/")
KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-1234")

# (1) + (2): custom client at the proxy with the run-id header.
client = AsyncOpenAI(
    base_url=f"{BASE}/v1",
    api_key=KEY,
    default_headers={"x-bench-run-id": RUN_ID},
)
set_default_openai_client(client)
set_default_openai_api("chat_completions")  # third-party endpoints need Chat Completions
set_tracing_disabled(True)  # tracing exporter would try to reach OpenAI directly


@function_tool
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


agent = Agent(
    name="Assistant",
    instructions="You are a helpful assistant. Use tools when relevant.",
    tools=[add],
    model="gemini-2.5-flash",
)


async def main() -> int:
    r1 = await Runner.run(agent, "What is 21 plus 21? Use the add tool.")
    print("TURN1:", r1.final_output)
    # (3) multi-turn: carry the prior turn's items forward
    r2 = await Runner.run(
        agent,
        r1.to_input_list() + [{"role": "user", "content": "Now add 100 to that result."}],
    )
    print("TURN2:", r2.final_output)
    print("OK openai_agents spike completed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
