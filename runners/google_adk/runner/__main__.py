"""Google ADK runner entry — `python -m runner`. Thin wrapper over bench_common."""
from __future__ import annotations

import sys
from importlib import metadata

from bench_common import run

from .llm import build_llm
from .tasks import task01


def _version() -> str:
    try:
        return metadata.version("google-adk")
    except metadata.PackageNotFoundError:
        return "unknown"


HANDLERS = {"01_hello_world": task01.run}

if __name__ == "__main__":
    sys.exit(run("google_adk", _version, build_llm, HANDLERS))
