"""Task 4 naive — LangChain, CSV injected into the prompt."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench_common import (
    RunnerArgs, variant_params, read_csv_text, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    csv_text = read_csv_text(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}\n\nCSV DATA:\n{csv_text}"

    resp = llm.invoke(prompt)
    text = resp.content if hasattr(resp, "content") else str(resp)
    answer = extract_answer_dict(str(text))

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    meta = getattr(resp, "usage_metadata", None)
    if meta:
        usage["input"] = int(meta.get("input_tokens", 0) or 0)
        usage["output"] = int(meta.get("output_tokens", 0) or 0)
        details = meta.get("input_token_details") or {}
        usage["cached"] = int(details.get("cache_read", 0) or 0)
    return answer, usage
