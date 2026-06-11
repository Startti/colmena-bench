"""Task 4 naive — Colmena, CSV injected into the prompt (single LLM call)."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

from bench_common import (
    RunnerArgs, variant_params, read_csv_text, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(task_def: dict[str, Any], caller: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    csv_text = read_csv_text(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    content = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}\n\nCSV DATA:\n{csv_text}"

    import colmena
    opts = colmena.LlmConfigOptions()
    opts.model = caller.model_alias
    opts.api_key = caller.api_key
    opts.temperature = 0.0

    out = caller.llm.call([{"role": "user", "content": content}], "openai", opts)
    if inspect.isawaitable(out):
        out = asyncio.get_event_loop().run_until_complete(out)
    answer = extract_answer_dict(str(out))
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
