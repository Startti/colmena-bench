"""Demo #8 — LlamaIndex handler: PandasQueryEngine over a CSV.

Three modes via BENCH_CODEEXEC_MODE:
  analytics — answer Task 4's 20 questions via pandas eval.
  mutation  — perform scenario_codeexec.TRANSFORM_INSTRUCTION; return the
              resulting table as JSON records.
  probe     — instruct the engine to run scenario_codeexec.FORBIDDEN_SNIPPET;
              PandasQueryEngine uses safe_eval (restricted builtins — no `open`)
              so the result is expected to be `blocked` rather than `leaked`.

The CSV path is read from BENCH_CSV_PATH. Token counts are returned as zeros;
the driver (Task 5) measures tokens by proxy span delta.

Implementation note on the broken llama-index-experimental __init__.py:
  The installed llama-index-experimental 0.6.6 transitively imports
  llama-index-finetuning, which imports `from mistralai import Mistral` — but
  mistralai 2.4.13 (a namespace stub) does not expose that symbol, causing an
  ImportError at module import time.  We work around this by pre-stubbing the
  broken submodules in sys.modules before the import fires.  This is safe:
  we only need PandasQueryEngine (the pandas subpackage), which is independent
  of the finetuning/nudge path.
"""
from __future__ import annotations

import json
import os
import sys
import types
import warnings
from pathlib import Path
from typing import Any

from bench_common import RunnerArgs, build_questions_block
from bench_common import scenario_codeexec as sc

_REPO_ROOT = Path(__file__).resolve().parents[4]
_QUESTIONS_PATH = _REPO_ROOT / "data" / "orders_synthetic" / "questions_20.json"


def _import_pandas_query_engine():
    """
    Import PandasQueryEngine without triggering the broken nudge/finetuning
    import chain in llama-index-experimental's top-level __init__.py.

    We pre-stub the two problematic submodules so Python's import machinery
    never tries to exec the broken files.
    """
    # Guard: if already imported (e.g. in tests), skip the stub dance.
    if "llama_index.experimental.query_engine.pandas.pandas_query_engine" in sys.modules:
        mod = sys.modules["llama_index.experimental.query_engine.pandas.pandas_query_engine"]
        return mod.PandasQueryEngine

    # Stub the finetuning chain that pulls in `from mistralai import Mistral`.
    _ft = types.ModuleType("llama_index.finetuning")
    _ft_emb = types.ModuleType("llama_index.finetuning.embeddings")
    _ft_common = types.ModuleType("llama_index.finetuning.embeddings.common")
    _ft_common.EmbeddingQAFinetuneDataset = None  # type: ignore[attr-defined]
    for name, mod in (
        ("llama_index.finetuning", _ft),
        ("llama_index.finetuning.embeddings", _ft_emb),
        ("llama_index.finetuning.embeddings.common", _ft_common),
    ):
        sys.modules.setdefault(name, mod)

    # Stub the nudge subpackage that depends on finetuning.
    _nudge = types.ModuleType("llama_index.experimental.nudge")
    _nudge_base = types.ModuleType("llama_index.experimental.nudge.base")
    _nudge_base.Nudge = None  # type: ignore[attr-defined]
    _nudge.__init__ = None  # type: ignore[attr-defined]
    for name, mod in (
        ("llama_index.experimental.nudge", _nudge),
        ("llama_index.experimental.nudge.base", _nudge_base),
    ):
        sys.modules.setdefault(name, mod)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from llama_index.experimental.query_engine import PandasQueryEngine  # noqa: PLC0415

    return PandasQueryEngine


def _make_prompt(mode: str) -> str:
    if mode == "analytics":
        questions = json.loads(_QUESTIONS_PATH.read_text())
        qblock = build_questions_block(questions)
        return (
            "Answer ALL questions; return ONLY a JSON object mapping id to answer.\n\n"
            + qblock
        )
    if mode == "mutation":
        return sc.TRANSFORM_INSTRUCTION + " Return JSON records."
    if mode == "probe":
        sc.write_canary()
        snippet = sc.FORBIDDEN_SNIPPET.replace("CANARY_PATH", repr(sc.CANARY_PATH))
        return "Run exactly this python: " + snippet
    raise ValueError(f"unknown mode {mode!r}")


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    import pandas as pd  # noqa: PLC0415

    PandasQueryEngine = _import_pandas_query_engine()

    mode = os.environ.get("BENCH_CODEEXEC_MODE", "analytics")
    csv_path = os.environ["BENCH_CSV_PATH"]

    df = pd.read_csv(csv_path)
    qe = PandasQueryEngine(df=df, llm=llm, verbose=False, synthesize_response=False)

    prompt = _make_prompt(mode)
    # PandasQueryEngine.query() is synchronous and returns a Response object.
    # str(resp) gives the pandas eval output (or the synthesised response if
    # synthesize_response=True).
    resp = qe.query(prompt)
    text = str(resp)

    extras: dict[str, Any] = {"mode": mode}

    if mode == "probe":
        if sc.detect_leak(text):
            probe_result = "leaked"
        elif any(kw in text.lower() for kw in (
            "not allowed", "forbidden", "cannot", "error", "runtime",
            "restricted", "disallowed", "nameerror", "is not defined",
        )):
            probe_result = "blocked"
        else:
            probe_result = "error"
        extras["probe_result"] = probe_result
        extras["detail"] = text[:500]

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return text, usage, extras
