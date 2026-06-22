"""Task 4 naive — LlamaIndex, CSV injected into the prompt."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole

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

    # Naive sends the whole CSV in-context: long prompt -> long generation.
    # OpenAILike defaults to a 60s request timeout, which is too tight here;
    # bump it on this call (task01/task05 keep the factory default).
    try:
        llm.timeout = max(getattr(llm, "timeout", 60) or 60, 300)
    except Exception:
        pass

    messages = [ChatMessage(role=MessageRole.USER, content=prompt)]
    resp = llm.chat(messages)
    text = resp.message.content if hasattr(resp, "message") else str(resp)
    answer = extract_answer_dict(str(text))

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    raw = getattr(resp, "raw", None)
    raw_usage = None
    if isinstance(raw, dict):
        raw_usage = raw.get("usage")
    elif raw is not None:
        raw_usage = getattr(raw, "usage", None)
    if raw_usage is not None:
        get = raw_usage.get if isinstance(raw_usage, dict) else lambda k, d=0: getattr(raw_usage, k, d)
        usage["input"] = int(get("prompt_tokens", 0) or 0)
        usage["output"] = int(get("completion_tokens", 0) or 0)
    return answer, usage
