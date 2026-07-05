"""Build the question block and extract a {question_id: answer} dict from text."""
from __future__ import annotations

import datetime
import json
import re
from typing import Any


def build_questions_block(questions: dict) -> str:
    return "\n".join(f"{q['id']}: {q['text']}" for q in questions["questions"])


def jsonify_answers(value: Any) -> Any:
    """Recursively convert pandas/numpy objects to JSON-native types.

    A code-generating runner that ``exec()``s model-written pandas often leaves
    raw ``Series``/``Timestamp``/``numpy`` objects in ``answers_dict``. Passing
    those to ``json.dumps(..., default=str)`` stringifies them to a ``repr`` the
    exact-match scorer rejects (e.g. a Series becomes a multi-line block, a
    Timestamp keeps its ``00:00:00`` time), which silently fails every dict/date
    question even though the computation was correct. Normalizing here produces
    the same clean JSON the non-codegen runners emit:

      Series/DataFrame -> dict (keys jsonified too)
      Timestamp/Period/date -> 'YYYY-MM-DD' / 'YYYY-MM' string
      numpy scalar/array -> python scalar/list
    """
    try:  # pandas/numpy are present in the code-exec venvs but keep this soft.
        import numpy as np  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        np = None
    try:
        import pandas as pd  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        pd = None

    if pd is not None:
        if isinstance(value, pd.Series):
            return {_json_key(k): jsonify_answers(v) for k, v in value.to_dict().items()}
        if isinstance(value, pd.DataFrame):
            return {_json_key(k): jsonify_answers(v) for k, v in value.to_dict().items()}
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, pd.Period):
            return str(value)
        if value is getattr(pd, "NaT", object()):
            return None
    if np is not None:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.ndarray):
            return [jsonify_answers(v) for v in value.tolist()]
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dict):
        return {_json_key(k): jsonify_answers(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonify_answers(v) for v in value]
    return value


def _json_key(key: Any) -> str:
    """JSON object keys must be strings; jsonify then coerce."""
    k = jsonify_answers(key)
    return k if isinstance(k, str) else str(k)


_QID = re.compile(r"^Q\d+$")


def extract_answer_dict(text: str) -> dict[str, Any]:
    """Pull the answers dict from a model message.

    A message may contain several JSON objects (e.g. a tool-call payload like
    {"query": "..."} plus the final answers). We collect every parseable JSON
    object and pick the one that looks most like answers — most `Q\\d+` keys,
    then most keys overall. Falls back to {} if nothing parses.
    """
    if not text:
        return {}
    dicts: list[dict] = []
    # All fenced blocks (greedy per fence).
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        _try_load(m.group(1), dicts)
    # Every brace-balanced span in the text.
    for span in _balanced_spans(text):
        _try_load(span, dicts)
    # Whole string.
    _try_load(text.strip(), dicts)
    if not dicts:
        return {}

    def score(d: dict) -> tuple[int, int]:
        qkeys = sum(1 for k in d if _QID.match(str(k)))
        return (qkeys, len(d))

    return max(dicts, key=score)


def _try_load(s: str, out: list[dict]) -> None:
    try:
        v = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return
    if isinstance(v, dict):
        out.append(v)


def _balanced_spans(text: str) -> list[str]:
    """Return every top-level brace-balanced {...} substring."""
    spans, depth, start = [], 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    spans.append(text[start : i + 1])
    return spans
