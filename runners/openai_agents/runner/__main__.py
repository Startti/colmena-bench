"""OpenAI Agents runner entry — `python -m runner`. Thin wrapper over bench_common."""
from __future__ import annotations

import sys
from importlib import metadata

from bench_common import run

from .llm import build_llm
from .tasks import task05, task06_refund, task07_tools, task08_codeexec, task10_secrets


def _version() -> str:
    try:
        return metadata.version("openai-agents")
    except metadata.PackageNotFoundError:
        return "unknown"


HANDLERS = {
    "05_context_scrubbing": task05.run,
    "06_refund": task06_refund.run,
    "07_tools": task07_tools.run,
    "08_codeexec": task08_codeexec.run,
    "10_secrets": task10_secrets.run,
}

if __name__ == "__main__":
    sys.exit(run("openai_agents", _version, build_llm, HANDLERS))
