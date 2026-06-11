"""CrewAI runner entry — `python -m runner`. Thin wrapper over bench_common."""
from __future__ import annotations

import sys
from importlib import metadata

from bench_common import run

from .llm import build_llm
from .tasks import task01, task04_naive, task04_expert


def _version() -> str:
    try:
        return metadata.version("crewai")
    except metadata.PackageNotFoundError:
        return "unknown"


HANDLERS = {
    "01_hello_world": task01.run,
    "04_csv_naive": task04_naive.run,
    "04_csv_expert": task04_expert.run,
}

if __name__ == "__main__":
    sys.exit(run("crewai", _version, build_llm, HANDLERS))
