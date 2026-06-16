"""Colmena runner entry — `python -m runner`. Thin wrapper over bench_common."""
from __future__ import annotations

import sys
from importlib import metadata

from bench_common import run

from .llm import build_llm
from .tasks import task01, task04_naive, task05


def _version() -> str:
    # Colmena's Python package is `colmena-ai`.
    for dist in ("colmena-ai", "colmena"):
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            continue
    return "unknown"


HANDLERS = {
    "01_hello_world": task01.run,
    "04_csv_naive": task04_naive.run,
    "05_context_scrubbing": task05.run,
}

if __name__ == "__main__":
    sys.exit(run("colmena", _version, build_llm, HANDLERS))
