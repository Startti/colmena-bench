"""Pydantic AI runner entry — `python -m runner`. Thin wrapper over bench_common."""
from __future__ import annotations

import sys
from importlib import metadata

from bench_common import run

from .llm import build_llm
from .tasks import task05


def _version() -> str:
    try:
        return metadata.version("pydantic-ai")
    except metadata.PackageNotFoundError:
        try:
            return metadata.version("pydantic-ai-slim")
        except metadata.PackageNotFoundError:
            return "unknown"


HANDLERS = {
    "05_context_scrubbing": task05.run,
}

if __name__ == "__main__":
    sys.exit(run("pydantic_ai", _version, build_llm, HANDLERS))
