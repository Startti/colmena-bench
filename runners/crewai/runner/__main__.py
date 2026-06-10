"""CLI entry — dispatches to the right task handler."""
from __future__ import annotations

import sys

from .common import main
from .llm import build_llm
from .tasks import task01

HANDLERS = {
    "01_hello_world": task01.run,
    # task02, task03, ... added in Phase 2.
}

if __name__ == "__main__":
    sys.exit(main(HANDLERS, build_llm))
