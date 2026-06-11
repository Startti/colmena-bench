"""Framework-agnostic runner core shared by every Python runner.

Each runner provides only the framework-specific bits — a name, a version
resolver, an LLM factory, and per-task handlers — and delegates the rest
(arg parsing, timing, scoring, output emission) to `run()`.

Usage in a runner's __main__.py:

    import sys
    from bench_common import run
    from .llm import build_llm
    from .tasks import task01

    def _version() -> str:
        from importlib import metadata
        try:
            return metadata.version("langchain")
        except metadata.PackageNotFoundError:
            return "unknown"

    HANDLERS = {"01_hello_world": task01.run}

    if __name__ == "__main__":
        sys.exit(run("langchain", _version, build_llm, HANDLERS))
"""
from .core import RunnerArgs, run, score_success, emit_output, load_task

__all__ = ["RunnerArgs", "run", "score_success", "emit_output", "load_task"]
