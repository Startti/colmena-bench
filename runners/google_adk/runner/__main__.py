"""Google ADK runner entry — `python -m runner`. Thin wrapper over bench_common."""
from __future__ import annotations

import sys
from importlib import metadata

from bench_common import run

from .llm import build_llm
from .tasks import task01, task04_expert, task04_naive, task05, task06_refund, task07_tools


def _version() -> str:
    try:
        return metadata.version("google-adk")
    except metadata.PackageNotFoundError:
        return "unknown"


HANDLERS = {
    "01_hello_world": task01.run,
    "04_csv_naive": task04_naive.run,
    "04_csv_expert": task04_expert.run,
    "05_context_scrubbing": task05.run,
    "06_refund": task06_refund.run,
    "07_tools": task07_tools.run,
}

if __name__ == "__main__":
    sys.exit(run("google_adk", _version, build_llm, HANDLERS))
