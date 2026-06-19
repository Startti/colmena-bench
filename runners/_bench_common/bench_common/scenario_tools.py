"""Demo #7 — generator for the many-tools needle-in-haystack experiment.

Produces a framework-agnostic toolset spec consumed identically by all runners:
N tools (mixed easy/medium/hard by param count) of which exactly one is the
deterministic `needle` that answers the question. Distractors are no-ops. Seeded
by a STABLE string so a given (n, difficulty, seed) is byte-stable across the 7
configs and across processes (fairness), but varies across trials.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

_VERBS = ["get", "list", "update", "create", "cancel", "search", "summarize", "export"]
_NOUNS = ["order", "customer", "shipment", "invoice", "ticket", "product",
          "payment", "account", "subscription", "refund", "campaign", "report"]
_ASPECT = {"get": "details of a", "list": "all", "update": "fields on a",
           "create": "a new", "cancel": "an existing", "search": "matching",
           "summarize": "a summary of a", "export": "a CSV of"}
_PARAM_POOL = [
    ("id", "string"), ("date_from", "string"), ("date_to", "string"),
    ("status", "string"), ("region", "string"), ("currency", "string"),
    ("limit", "integer"), ("offset", "integer"), ("include_archived", "boolean"),
    ("sort_by", "string"), ("tags", "array"), ("priority", "integer"),
]
_DIFF_RANGE = {"easy": (1, 2), "medium": (3, 5), "hard": (6, 10)}


def _make_params(k: int, rng: random.Random) -> list[dict]:
    chosen = rng.sample(_PARAM_POOL, min(k, len(_PARAM_POOL)))
    out = []
    for i, (nm, ty) in enumerate(chosen):
        out.append({"name": nm, "type": ty, "required": i == 0,
                    "description": f"The {nm.replace('_', ' ')} ({ty})."})
    return out


def _value_for(p: dict) -> Any:
    return {"string": "X7", "integer": 7, "boolean": True, "array": ["a"]}[p["type"]]


def generate_toolset(n: int, needle_difficulty: str, seed: int) -> dict:
    rng = random.Random(f"{n}-{needle_difficulty}-{seed}")
    combos = [(v, nn) for v in _VERBS for nn in _NOUNS]
    rng.shuffle(combos)
    diffs = ["easy", "medium", "hard"]
    tools: list[dict] = []
    used: set[str] = set()
    i = 0
    while len(tools) < n:
        v, nn = combos[i % len(combos)]
        suffix = i // len(combos)
        name = f"{v}_{nn}" + (f"_{suffix}" if suffix else "")
        i += 1
        if name in used:
            continue
        used.add(name)
        diff = diffs[len(tools) % 3]
        lo, hi = _DIFF_RANGE[diff]
        params = _make_params(rng.randint(lo, hi), rng)
        tools.append({
            "name": name,
            "summary": f"{v.capitalize()} {_ASPECT[v]} {nn} record (id {len(tools)}). Use for {nn} {v} requests.",
            "description": f"{v.capitalize()} {nn}. Parameters: " +
                           ", ".join(p["name"] for p in params) + ".",
            "params": params, "is_needle": False, "answer": "not applicable",
        })
    needle_idx = rng.randrange(n)
    nt = tools[needle_idx]
    lo, hi = _DIFF_RANGE[needle_difficulty]
    nt["params"] = _make_params(rng.randint(lo, hi), rng)
    nt["is_needle"] = True
    answer = f"{rng.randint(1000, 9999)}.00"
    nt["answer"] = answer
    expected_args = {p["name"]: _value_for(p) for p in nt["params"] if p["required"]}
    arg_phrase = ", ".join(f"{k}={v}" for k, v in expected_args.items())
    question = (f"Use the `{nt['name']}` tool with {arg_phrase} and report the "
                f"resulting total amount in USD. Answer with just the number.")
    return {
        "n_tools": n, "needle_difficulty": needle_difficulty, "seed": seed,
        "needle": nt["name"], "expected_args": expected_args,
        "expected_answer": answer, "question": question, "tools": tools,
    }


def log_tool_call(tool_name: str, args: dict) -> None:
    path = os.environ.get("BENCH_TOOLCALL_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": tool_name, "args": args}) + "\n")


def read_tool_calls(path: "str | Path") -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def score(spec: dict, tool_calls: list[dict], final_answer: str) -> dict:
    needle = spec["needle"]
    called = [c for c in tool_calls if c.get("tool") == needle]
    selection_ok = len(called) > 0
    arg_ok = any(
        all(str(c.get("args", {}).get(k)) == str(v) for k, v in spec["expected_args"].items())
        for c in called
    )
    answer_ok = spec["expected_answer"] in (final_answer or "")
    return {"selection_ok": selection_ok, "arg_ok": arg_ok, "answer_ok": answer_ok}
