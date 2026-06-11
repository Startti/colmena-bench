# Task 4 Killer Demo — Implementation Plan (MVP)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the naive-vs-expert CSV analytical task (Task 4) end-to-end for CrewAI (naive+expert) and Colmena (naive) across sizes S/M/L, with a centralized 20-question scorer, proving the tokens-vs-rows asymptote.

**Architecture:** Two task YAMLs (`04_csv_naive`, `04_csv_expert`) drive each runner to answer 20 questions and return a JSON answer dict. Naive injects the CSV into the prompt; expert exposes a `run_sql` tool over in-memory SQLite. The runner never sees ground truth — the orchestrator scores `dataset_qa` runs post-hoc with `task04_scorer.py` and overwrites `success`. Shared helpers live in `bench_common`.

**Tech Stack:** Python 3.11, SQLite (stdlib), pydantic-free helpers, CrewAI 1.14.6, colmena (native), the existing proxy + orchestrator.

**Spec:** `docs/superpowers/specs/2026-06-11-task4-killer-demo-design.md`

---

## File Structure

- `harness/schemas/task.schema.json` — add `dataset_qa` to `success.kind` enum.
- `runners/_bench_common/bench_common/datasets.py` — `read_csv_text`, `load_orders_sqlite`.
- `runners/_bench_common/bench_common/answers.py` — `extract_answer_dict`.
- `runners/_bench_common/bench_common/__init__.py` — re-export the new helpers.
- `runners/_bench_common/tests/test_datasets.py`, `test_answers.py`.
- `harness/scoring/__init__.py`, `harness/scoring/task04_scorer.py`, `harness/scoring/tests/test_task04_scorer.py`.
- `harness/tasks/04_csv_naive.yaml`, `harness/tasks/04_csv_expert.yaml`.
- `runners/crewai/runner/tasks/task04_naive.py`, `task04_expert.py`.
- `runners/colmena/runner/tasks/task04_naive.py`.
- `runners/crewai/runner/__main__.py`, `runners/colmena/runner/__main__.py` — register handlers.
- `bench_common.core` — `RunnerArgs` needs the variant's `dataset_path`; add a `variant_params(task, variant)` helper.
- `harness/orchestrator/full_run.py` — score `dataset_qa` tasks; allow running multiple task ids.

---

## Task 1: Add `dataset_qa` success kind to the schema

**Files:**
- Modify: `harness/schemas/task.schema.json`
- Test: `harness/tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

Add to `harness/tests/test_schemas.py`:

```python
def test_task_accepts_dataset_qa_success_kind(schemas):
    task = _sample_task()
    task["id"] = "04_csv_naive"
    task["success"] = {"kind": "dataset_qa", "ground_truth_path": "data/orders_synthetic/ground_truth.json"}
    Draft202012Validator(schemas["task.schema.json"]).validate(task)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd harness && ../.venv-bench/bin/python -m pytest tests/test_schemas.py::test_task_accepts_dataset_qa_success_kind -q`
Expected: FAIL — `'dataset_qa' is not one of [...]`.

- [ ] **Step 3: Edit the schema**

In `harness/schemas/task.schema.json`, find the `success.properties.kind.enum` and add `"dataset_qa"`:

```json
"kind": { "type": "string", "enum": ["regex", "exact_numeric", "llm_judge", "set_equality", "dataset_qa"] },
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd harness && ../.venv-bench/bin/python -m pytest tests/test_schemas.py -q`
Expected: PASS (all schema tests).

- [ ] **Step 5: Commit**

```bash
git add harness/schemas/task.schema.json harness/tests/test_schemas.py
git commit -m "feat(schema): add dataset_qa success kind for Task 4"
```

---

## Task 2: `bench_common.datasets` — CSV text + SQLite loader

**Files:**
- Create: `runners/_bench_common/bench_common/datasets.py`
- Modify: `runners/_bench_common/bench_common/__init__.py`
- Test: `runners/_bench_common/tests/test_datasets.py`

- [ ] **Step 1: Write the failing test**

Create `runners/_bench_common/tests/test_datasets.py`:

```python
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
REPO = PKG.parent.parent

from bench_common.datasets import read_csv_text, load_orders_sqlite  # noqa: E402

CSV = REPO / "data/orders_synthetic/seeds/S.csv"


def test_read_csv_text_has_header_and_rows():
    text = read_csv_text(CSV)
    assert text.startswith("order_id,customer_id,")
    assert len(text.splitlines()) == 501  # header + 500 rows


def test_load_orders_sqlite_counts_rows():
    conn, run_sql = load_orders_sqlite(CSV)
    out = run_sql("SELECT COUNT(*) AS n FROM orders")
    assert "500" in out
    conn.close()


def test_run_sql_typed_aggregate():
    conn, run_sql = load_orders_sqlite(CSV)
    out = run_sql("SELECT COUNT(*) AS n FROM orders WHERE status='cancelled'")
    assert out.strip() != ""
    conn.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_datasets.py -q`
Expected: FAIL — `ModuleNotFoundError: bench_common.datasets`.

- [ ] **Step 3: Implement `datasets.py`**

Create `runners/_bench_common/bench_common/datasets.py`:

```python
"""Dataset helpers shared by runners: CSV-as-text (naive) and SQLite (expert)."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Callable


def read_csv_text(csv_path: Path | str) -> str:
    return Path(csv_path).read_text(encoding="utf-8")


def load_orders_sqlite(csv_path: Path | str) -> tuple[sqlite3.Connection, Callable[[str], str]]:
    """Load the CSV into an in-memory table `orders`. Returns (conn, run_sql).

    `run_sql(query)` runs a read-only SELECT and returns a compact text table
    (header + rows), or an `ERROR: ...` string the agent can read and recover
    from. All columns are stored as TEXT; SQL CAST as needed for math.
    """
    path = Path(csv_path)
    conn = sqlite3.connect(":memory:")
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        cols = ", ".join(f'"{c}" TEXT' for c in header)
        conn.execute(f"CREATE TABLE orders ({cols})")
        placeholders = ", ".join("?" for _ in header)
        conn.executemany(f"INSERT INTO orders VALUES ({placeholders})", reader)
    conn.commit()

    def run_sql(query: str) -> str:
        try:
            cur = conn.execute(query)
        except Exception as e:  # noqa: BLE001 — surface to the agent, don't crash
            return f"ERROR: {type(e).__name__}: {e}"
        rows = cur.fetchall()
        names = [d[0] for d in cur.description] if cur.description else []
        lines = [" | ".join(names)] if names else []
        for r in rows[:200]:  # cap output so a bad query can't blow up tokens
            lines.append(" | ".join("" if v is None else str(v) for v in r))
        if len(rows) > 200:
            lines.append(f"... ({len(rows)} rows total, showing 200)")
        return "\n".join(lines) if lines else "(no rows)"

    return conn, run_sql
```

- [ ] **Step 4: Re-export from `__init__.py`**

In `runners/_bench_common/bench_common/__init__.py`, add to the imports and `__all__`:

```python
from .datasets import read_csv_text, load_orders_sqlite
```
and append `"read_csv_text"`, `"load_orders_sqlite"` to `__all__`.

- [ ] **Step 5: Run to verify it passes**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_datasets.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add runners/_bench_common/bench_common/datasets.py runners/_bench_common/bench_common/__init__.py runners/_bench_common/tests/test_datasets.py
git commit -m "feat(bench_common): CSV text + in-memory SQLite dataset helpers"
```

---

## Task 3: `bench_common.answers` — tolerant answer-dict extraction

**Files:**
- Create: `runners/_bench_common/bench_common/answers.py`
- Modify: `runners/_bench_common/bench_common/__init__.py`
- Test: `runners/_bench_common/tests/test_answers.py`

- [ ] **Step 1: Write the failing test**

Create `runners/_bench_common/tests/test_answers.py`:

```python
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
from bench_common.answers import extract_answer_dict  # noqa: E402


def test_plain_json():
    assert extract_answer_dict('{"Q01": 500, "Q02": 494}') == {"Q01": 500, "Q02": 494}


def test_json_in_code_fence():
    text = "Here are the answers:\n```json\n{\"Q01\": 500}\n```\nDone."
    assert extract_answer_dict(text) == {"Q01": 500}


def test_json_embedded_in_prose():
    text = 'The result is {"Q01": 500, "Q14": 1124383.23} based on the data.'
    assert extract_answer_dict(text) == {"Q01": 500, "Q14": 1124383.23}


def test_no_json_returns_empty():
    assert extract_answer_dict("I could not answer.") == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_answers.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `answers.py`**

Create `runners/_bench_common/bench_common/answers.py`:

```python
"""Extract a {question_id: answer} dict from a model's free-form message."""
from __future__ import annotations

import json
import re
from typing import Any


def extract_answer_dict(text: str) -> dict[str, Any]:
    if not text:
        return {}
    # 1) fenced ```json ... ``` or ``` ... ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = []
    if fence:
        candidates.append(fence.group(1))
    # 2) the widest brace-balanced span in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    # 3) the whole string
    candidates.append(text.strip())
    for c in candidates:
        try:
            val = json.loads(c)
            if isinstance(val, dict):
                return val
        except (json.JSONDecodeError, ValueError):
            continue
    return {}
```

- [ ] **Step 4: Re-export from `__init__.py`**

Add `from .answers import extract_answer_dict` and append `"extract_answer_dict"` to `__all__`.

- [ ] **Step 5: Run to verify it passes**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_answers.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add runners/_bench_common/bench_common/answers.py runners/_bench_common/bench_common/__init__.py runners/_bench_common/tests/test_answers.py
git commit -m "feat(bench_common): tolerant answer-dict extraction"
```

---

## Task 4: `task04_scorer` — score 20 answers vs ground truth

**Files:**
- Create: `harness/scoring/__init__.py`, `harness/scoring/task04_scorer.py`
- Test: `harness/scoring/tests/__init__.py`, `harness/scoring/tests/test_task04_scorer.py`

- [ ] **Step 1: Write the failing test**

Create `harness/scoring/tests/__init__.py` (empty) and `harness/scoring/tests/test_task04_scorer.py`:

```python
import json
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HARNESS))
REPO = HARNESS.parent

from scoring.task04_scorer import score_answers  # noqa: E402

QUESTIONS = json.loads((REPO / "data/orders_synthetic/questions_20.json").read_text())
GT = json.loads((REPO / "data/orders_synthetic/ground_truth.json").read_text())
GT_S = GT["by_size"]["S"]["answers"]


def test_all_correct_scores_one():
    res = score_answers(GT_S, GT_S, QUESTIONS)  # answers == truth
    assert res["success_rate"] == 1.0
    assert res["correct"] == 20


def test_string_form_numbers_pass():
    answers = dict(GT_S)
    answers["Q01"] = "500"
    answers["Q14"] = "$1,124,383.23"
    res = score_answers(answers, GT_S, QUESTIONS)
    assert res["per_question"]["Q01"] is True
    assert res["per_question"]["Q14"] is True


def test_float_within_tolerance():
    answers = dict(GT_S)
    answers["Q14"] = GT_S["Q14"] * 1.005  # +0.5% within 1%
    assert score_answers(answers, GT_S, QUESTIONS)["per_question"]["Q14"] is True
    answers["Q14"] = GT_S["Q14"] * 1.05  # +5% outside 1%
    assert score_answers(answers, GT_S, QUESTIONS)["per_question"]["Q14"] is False


def test_missing_answer_is_wrong():
    answers = dict(GT_S)
    del answers["Q20"]
    res = score_answers(answers, GT_S, QUESTIONS)
    assert res["per_question"]["Q20"] is False
    assert res["correct"] == 19


def test_object_partial_keys_fail():
    answers = dict(GT_S)
    obj = dict(GT_S["Q06"])
    first_key = next(iter(obj))
    obj[first_key] = obj[first_key] * 2  # corrupt one value
    answers["Q06"] = obj
    assert score_answers(answers, GT_S, QUESTIONS)["per_question"]["Q06"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd harness && ../.venv-bench/bin/python -m pytest scoring/tests/test_task04_scorer.py -q`
Expected: FAIL — `ModuleNotFoundError: scoring.task04_scorer`.

- [ ] **Step 3: Implement the scorer**

Create `harness/scoring/__init__.py` (empty) and `harness/scoring/task04_scorer.py`:

```python
"""Score Task 4's 20 answers against ground truth. Framework-agnostic.

The runner never sees ground truth; the orchestrator calls score_answers()
after a run completes. Comparison rules per questions_20.json answer_type:
integer exact, float within 1% relative, date string-equal, object/dict
key-by-key (numeric or string), object_top_n top-N keys, array ordered.
"""
from __future__ import annotations

import re
from typing import Any

FLOAT_REL_TOL = 0.01


def _to_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = re.sub(r"[,$%\s]", "", v.strip())
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _num_eq(a: Any, b: Any, *, is_int: bool) -> bool:
    na, nb = _to_number(a), _to_number(b)
    if na is None or nb is None:
        return False
    if is_int:
        return round(na) == round(nb)
    if nb == 0:
        return abs(na) < 1e-9
    return abs(na - nb) / abs(nb) <= FLOAT_REL_TOL


def _str_eq(a: Any, b: Any) -> bool:
    return str(a).strip() == str(b).strip()


def _value_eq(a: Any, b: Any) -> bool:
    """Generic value compare: numbers by float tol, else string."""
    if _to_number(b) is not None:
        return _num_eq(a, b, is_int=float(_to_number(b)).is_integer() and isinstance(b, int))
    return _str_eq(a, b)


def _score_one(answer: Any, truth: Any, atype: str, top_n: int | None) -> bool:
    if answer is None:
        return False
    if atype == "integer":
        return _num_eq(answer, truth, is_int=True)
    if atype == "float":
        return _num_eq(answer, truth, is_int=False)
    if atype == "date":
        return _str_eq(answer, truth)
    if atype in ("object", "object_top_n"):
        if not isinstance(answer, dict) or not isinstance(truth, dict):
            return False
        keys = list(truth.keys())
        if atype == "object_top_n" and top_n:
            keys = keys[:top_n]
        for k in keys:
            if k not in answer or not _value_eq(answer[k], truth[k]):
                return False
        return True
    if atype == "array":
        if not isinstance(answer, list):
            return False
        truth_list = truth if isinstance(truth, list) else list(truth)
        if len(answer) != len(truth_list):
            return False
        return all(_str_eq(a, b) for a, b in zip(answer, truth_list))
    # Unknown type → string compare as a safe default.
    return _str_eq(answer, truth)


def score_answers(answers: dict, truth: dict, questions: dict) -> dict:
    per_question: dict[str, bool] = {}
    for q in questions["questions"]:
        qid = q["id"]
        ok = _score_one(
            answers.get(qid),
            truth.get(qid),
            q["answer_type"],
            q.get("top_n"),
        )
        per_question[qid] = bool(ok)
    correct = sum(1 for v in per_question.values() if v)
    total = len(questions["questions"])
    return {
        "per_question": per_question,
        "correct": correct,
        "total": total,
        "success_rate": correct / total if total else 0.0,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd harness && ../.venv-bench/bin/python -m pytest scoring/tests/test_task04_scorer.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add harness/scoring/
git commit -m "feat(scoring): Task 4 twenty-question scorer with per-type rules"
```

---

## Task 5: Variant-params helper in `bench_common.core`

**Files:**
- Modify: `runners/_bench_common/bench_common/core.py`, `.../__init__.py`
- Test: `runners/_bench_common/tests/test_variant_params.py`

- [ ] **Step 1: Write the failing test**

Create `runners/_bench_common/tests/test_variant_params.py`:

```python
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
from bench_common import variant_params  # noqa: E402


def test_variant_params_returns_matching_entry():
    task = {"variants": [{"name": "S", "dataset_path": "seeds/S.csv"},
                          {"name": "M", "dataset_path": "seeds/M.csv"}]}
    assert variant_params(task, "M") == {"name": "M", "dataset_path": "seeds/M.csv"}


def test_variant_params_missing_returns_empty():
    assert variant_params({"variants": [{"name": "S"}]}, "L") == {}
    assert variant_params({}, "S") == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_variant_params.py -q`
Expected: FAIL — `ImportError: cannot import name 'variant_params'`.

- [ ] **Step 3: Implement in `core.py`**

Add to `runners/_bench_common/bench_common/core.py`:

```python
def variant_params(task: dict, variant: str) -> dict:
    """Return the task's variant entry matching `variant`, or {} if absent."""
    for v in task.get("variants", []) or []:
        if v.get("name") == variant:
            return v
    return {}
```

In `__init__.py`, add `variant_params` to the `from .core import ...` line and `__all__`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_variant_params.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add runners/_bench_common/bench_common/core.py runners/_bench_common/bench_common/__init__.py runners/_bench_common/tests/test_variant_params.py
git commit -m "feat(bench_common): variant_params lookup helper"
```

---

## Task 6: Task 4 YAML definitions

**Files:**
- Create: `harness/tasks/04_csv_naive.yaml`, `harness/tasks/04_csv_expert.yaml`

- [ ] **Step 1: Write `04_csv_naive.yaml`**

Create `harness/tasks/04_csv_naive.yaml`:

```yaml
# Task 4 (naive) — answer 20 analytical questions with the full CSV in context.
# Tokens scale with rows; expected to break at L (context overflow).
id: "04_csv_naive"
title: "CSV analytical — naive (CSV in context)"
version: "0.1.0"
description: >
  The agent receives the entire CSV as text plus 20 analytical questions and
  must return a JSON object mapping question id to answer.
variants:
  - name: S
    dataset_path: data/orders_synthetic/seeds/S.csv
  - name: M
    dataset_path: data/orders_synthetic/seeds/M.csv
  - name: L
    dataset_path: data/orders_synthetic/seeds/L.csv
prompt: |
  You are a data analyst. Answer ALL of the questions using ONLY the CSV data
  provided. Return ONLY a JSON object mapping each question id to its answer,
  e.g. {"Q01": 500, "Q02": 494, ...}. Numbers must be plain numbers (no
  currency symbols). For questions asking for a mapping, return a JSON object.
tools: []
metrics: [latency, tokens, cost_usd, ram_peak_mb, success]
success:
  kind: dataset_qa
  ground_truth_path: data/orders_synthetic/ground_truth.json
model_alias: gemini-2.5-flash
timeout_seconds: 180
n_runs: 3
```

- [ ] **Step 2: Write `04_csv_expert.yaml`**

Create `harness/tasks/04_csv_expert.yaml` (identical except id/title/description; the runner decides naive-vs-tool by task id):

```yaml
# Task 4 (expert) — answer 20 questions via a run_sql tool over SQLite.
# CSV is NOT in context; tokens scale with questions, ~flat across sizes.
id: "04_csv_expert"
title: "CSV analytical — expert (run_sql tool)"
version: "0.1.0"
description: >
  The agent has a run_sql(query) tool over an in-memory SQLite table `orders`
  (all columns TEXT; CAST for math). It must answer 20 analytical questions
  and return a JSON object mapping question id to answer.
variants:
  - name: S
    dataset_path: data/orders_synthetic/seeds/S.csv
  - name: M
    dataset_path: data/orders_synthetic/seeds/M.csv
  - name: L
    dataset_path: data/orders_synthetic/seeds/L.csv
prompt: |
  You are a data analyst with a run_sql(query) tool over a SQLite table named
  `orders` (every column is TEXT — use CAST(... AS REAL/INTEGER) for math).
  Use the tool to answer ALL questions. Then return ONLY a JSON object mapping
  each question id to its answer, e.g. {"Q01": 500, ...}. Numbers must be plain
  numbers. For mapping questions, return a JSON object.
tools:
  - name: run_sql
metrics: [latency, tokens, cost_usd, ram_peak_mb, success]
success:
  kind: dataset_qa
  ground_truth_path: data/orders_synthetic/ground_truth.json
model_alias: gemini-2.5-flash
timeout_seconds: 300
n_runs: 3
```

- [ ] **Step 3: Validate both against the schema**

Run:
```bash
.venv-bench/bin/python -c "
import json, yaml
from jsonschema import Draft202012Validator
s = json.load(open('harness/schemas/task.schema.json'))
for f in ('04_csv_naive','04_csv_expert'):
    Draft202012Validator(s).validate(yaml.safe_load(open(f'harness/tasks/{f}.yaml')))
    print(f, 'valid')
"
```
Expected: both print `valid`.

- [ ] **Step 4: Commit**

```bash
git add harness/tasks/04_csv_naive.yaml harness/tasks/04_csv_expert.yaml
git commit -m "feat(tasks): Task 4 naive + expert YAML definitions"
```

---

## Task 7: Build the 20-question prompt (shared helper)

**Files:**
- Modify: `runners/_bench_common/bench_common/answers.py`, `.../__init__.py`
- Test: `runners/_bench_common/tests/test_answers.py`

The question text the agent sees is the same for naive and expert and every
framework, so build it once.

- [ ] **Step 1: Write the failing test**

Add to `runners/_bench_common/tests/test_answers.py`:

```python
from bench_common.answers import build_questions_block  # noqa: E402
import json as _json
from pathlib import Path as _Path

_REPO = _Path(__file__).resolve().parents[3]


def test_build_questions_block_lists_all_20():
    qs = _json.loads((_REPO / "data/orders_synthetic/questions_20.json").read_text())
    block = build_questions_block(qs)
    for q in qs["questions"]:
        assert q["id"] in block
        assert q["text"] in block
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_answers.py::test_build_questions_block_lists_all_20 -q`
Expected: FAIL — `ImportError: cannot import name 'build_questions_block'`.

- [ ] **Step 3: Implement**

Add to `runners/_bench_common/bench_common/answers.py`:

```python
def build_questions_block(questions: dict) -> str:
    lines = []
    for q in questions["questions"]:
        lines.append(f"{q['id']}: {q['text']}")
    return "\n".join(lines)
```

Add `build_questions_block` to `__init__.py`'s import + `__all__`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd runners/_bench_common && ../../.venv-bench/bin/python -m pytest tests/test_answers.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add runners/_bench_common/bench_common/answers.py runners/_bench_common/bench_common/__init__.py runners/_bench_common/tests/test_answers.py
git commit -m "feat(bench_common): build_questions_block helper"
```

---

## Task 8: CrewAI naive handler

**Files:**
- Create: `runners/crewai/runner/tasks/task04_naive.py`
- Modify: `runners/crewai/runner/__main__.py`

- [ ] **Step 1: Implement the handler**

Create `runners/crewai/runner/tasks/task04_naive.py`:

```python
"""Task 4 naive — CrewAI, CSV injected into the prompt."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, Task

from bench_common import (
    RunnerArgs, variant_params, read_csv_text, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    csv_text = read_csv_text(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    prompt = (
        f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}\n\nCSV DATA:\n{csv_text}"
    )
    agent = Agent(role="data analyst", goal="answer questions from CSV",
                  backstory="Expert analyst.", llm=llm, allow_delegation=False, verbose=False)
    crew_task = Task(description=prompt, expected_output="A JSON object of answers.", agent=agent)
    crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)

    result = crew.kickoff()
    answer = extract_answer_dict(str(result))
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
```

- [ ] **Step 2: Register the handler**

In `runners/crewai/runner/__main__.py`, import and add to `HANDLERS`:

```python
from .tasks import task01, task04_naive
...
HANDLERS = {
    "01_hello_world": task01.run,
    "04_csv_naive": task04_naive.run,
}
```

- [ ] **Step 3: Smoke test on size S (needs proxy running)**

Start the proxy first: `PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=t4 ./proxy/start_proxy.sh &` then:

```bash
BENCH_RUN_ID=t4 LITELLM_PROXY_API_KEY="$(grep ^LITELLM_MASTER_KEY= .env | cut -d= -f2-)" \
PYTHONPATH=runners/crewai:runners/_bench_common \
runners/crewai/.venv/bin/python -m runner \
  --task harness/tasks/04_csv_naive.yaml --variant S --run-id t4-cn-s \
  --model-alias gemini-2.5-flash --proxy-base-url http://127.0.0.1:4000 \
  --output /tmp/t4_crewai_naive_s.json --timeout-seconds 180
.venv-bench/bin/python -c "import json; d=json.load(open('/tmp/t4_crewai_naive_s.json')); print('answers:', len(d['answer']) if isinstance(d['answer'],dict) else d['answer']); print('error:', d['error'])"
```
Expected: `answers: 20` (or close), `error: None`.

- [ ] **Step 4: Commit**

```bash
git add runners/crewai/runner/tasks/task04_naive.py runners/crewai/runner/__main__.py
git commit -m "feat(crewai): Task 4 naive handler"
```

---

## Task 9: CrewAI expert handler (run_sql tool)

**Files:**
- Create: `runners/crewai/runner/tasks/task04_expert.py`
- Modify: `runners/crewai/runner/__main__.py`

- [ ] **Step 1: Implement the handler**

Create `runners/crewai/runner/tasks/task04_expert.py`:

```python
"""Task 4 expert — CrewAI, run_sql tool over SQLite (CSV not in context)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, Task
from crewai.tools import tool

from bench_common import (
    RunnerArgs, variant_params, load_orders_sqlite, build_questions_block, extract_answer_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int]]:
    vp = variant_params(task_def, args.variant)
    conn, run_sql = load_orders_sqlite(REPO_ROOT / vp["dataset_path"])
    questions = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
    qblock = build_questions_block(questions)

    @tool("run_sql")
    def run_sql_tool(query: str) -> str:
        """Run a read-only SQL SELECT against the `orders` table and return rows as text."""
        return run_sql(query)

    prompt = f"{task_def['prompt']}\n\nQUESTIONS:\n{qblock}"
    agent = Agent(role="data analyst", goal="answer questions via SQL",
                  backstory="Expert SQL analyst.", llm=llm, tools=[run_sql_tool],
                  allow_delegation=False, verbose=False)
    crew_task = Task(description=prompt, expected_output="A JSON object of answers.", agent=agent)
    crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)

    try:
        result = crew.kickoff()
        answer = extract_answer_dict(str(result))
    finally:
        conn.close()
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    return answer, usage
```

- [ ] **Step 2: Register the handler**

In `runners/crewai/runner/__main__.py` add `task04_expert` to the import and `HANDLERS["04_csv_expert"] = task04_expert.run`.

- [ ] **Step 3: Smoke test on size S (proxy running)**

```bash
BENCH_RUN_ID=t4 LITELLM_PROXY_API_KEY="$(grep ^LITELLM_MASTER_KEY= .env | cut -d= -f2-)" \
PYTHONPATH=runners/crewai:runners/_bench_common \
runners/crewai/.venv/bin/python -m runner \
  --task harness/tasks/04_csv_expert.yaml --variant S --run-id t4-ce-s \
  --model-alias gemini-2.5-flash --proxy-base-url http://127.0.0.1:4000 \
  --output /tmp/t4_crewai_expert_s.json --timeout-seconds 300
.venv-bench/bin/python -c "import json; d=json.load(open('/tmp/t4_crewai_expert_s.json')); print('answers:', len(d['answer']) if isinstance(d['answer'],dict) else d['answer']); print('error:', d['error'])"
```
Expected: `answers: 20` (or close), `error: None`. (Expert input tokens should be far lower than naive — the CSV isn't in context.)

- [ ] **Step 4: Commit**

```bash
git add runners/crewai/runner/tasks/task04_expert.py runners/crewai/runner/__main__.py
git commit -m "feat(crewai): Task 4 expert handler with run_sql tool"
```

---

## Task 10: Colmena naive handler

**Files:**
- Create: `runners/colmena/runner/tasks/task04_naive.py`
- Modify: `runners/colmena/runner/__main__.py`

- [ ] **Step 1: Implement the handler**

Create `runners/colmena/runner/tasks/task04_naive.py`:

```python
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
```

- [ ] **Step 2: Register the handler**

In `runners/colmena/runner/__main__.py` add `task04_naive` to the import and `HANDLERS["04_csv_naive"] = task04_naive.run`.

- [ ] **Step 3: Smoke test on size S (proxy running)**

```bash
BENCH_RUN_ID=t4 LITELLM_PROXY_API_KEY="$(grep ^LITELLM_MASTER_KEY= .env | cut -d= -f2-)" \
PYTHONPATH=runners/colmena:runners/_bench_common \
runners/colmena/.venv/bin/python -m runner \
  --task harness/tasks/04_csv_naive.yaml --variant S --run-id t4-coln-s \
  --model-alias gemini-2.5-flash --proxy-base-url http://127.0.0.1:4000 \
  --output /tmp/t4_colmena_naive_s.json --timeout-seconds 180
.venv-bench/bin/python -c "import json; d=json.load(open('/tmp/t4_colmena_naive_s.json')); print('answers:', len(d['answer']) if isinstance(d['answer'],dict) else d['answer']); print('error:', d['error'])"
```
Expected: `answers: 20` (or close), `error: None`.

- [ ] **Step 4: Commit**

```bash
git add runners/colmena/runner/tasks/task04_naive.py runners/colmena/runner/__main__.py
git commit -m "feat(colmena): Task 4 naive handler"
```

---

## Task 11: Orchestrator — score dataset_qa runs + multi-task report

**Files:**
- Modify: `harness/orchestrator/full_run.py`

- [ ] **Step 1: Add scoring import and ground-truth loading**

At the top of `full_run.py`, after the existing imports, add:

```python
sys.path.insert(0, str(HARNESS_DIR / "scoring"))
from task04_scorer import score_answers  # noqa: E402

QUESTIONS = json.loads((REPO_ROOT / "data/orders_synthetic/questions_20.json").read_text())
GROUND_TRUTH = json.loads((REPO_ROOT / "data/orders_synthetic/ground_truth.json").read_text())
```

- [ ] **Step 2: Score `dataset_qa` runs during enrichment**

In `run_framework`, after building `ro` and merging proxy tokens, before appending, insert scoring. Locate the block:

```python
        ro["_span_count"] = len(spans)
        enriched.append(ro)
        out_path.write_text(json.dumps(ro, indent=2))
```

Replace it with:

```python
        ro["_span_count"] = len(spans)
        _maybe_score_dataset_qa(ro, task_def, variant)
        enriched.append(ro)
        out_path.write_text(json.dumps(ro, indent=2))
```

`run_framework` doesn't currently have `task_def`/`variant` in scope — pass them
in. Change the signature and the call site to include `task_def: dict` and
`variant: str`, and load the task once in `main`. Then add this function:

```python
def _maybe_score_dataset_qa(ro: dict, task_def: dict, variant: str) -> None:
    if task_def.get("success", {}).get("kind") != "dataset_qa":
        return
    if ro.get("error"):
        ro["success"] = {"ok": False, "reason": ro["error"], "judge_score": 0.0}
        return
    answers = ro.get("answer")
    if not isinstance(answers, dict):
        ro["success"] = {"ok": False, "reason": "no parseable answer dict", "judge_score": 0.0}
        return
    truth = GROUND_TRUTH["by_size"][variant]["answers"]
    res = score_answers(answers, truth, QUESTIONS)
    ro["success"] = {"ok": True, "judge_score": res["success_rate"]}
    ro["extras"]["per_question"] = res["per_question"]
    ro["extras"]["correct"] = res["correct"]
```

- [ ] **Step 3: Thread `task_def` + `variant` through `run_framework`**

Change `run_framework(...)` signature to accept `task_def` and `variant`, and in
`main()` load the task with `json`/`yaml` once and pass them. The task YAML is
read with the same loader the runner uses; add at the top of `main`:

```python
    import yaml
    task_def = yaml.safe_load(args.task.read_text())
```

and pass `task_def=task_def, variant=args.variant` into each `run_framework`
call. (Add a `--variant` arg to `full_run.py`'s parser, default `"S"`; for
Task 1 it stays `default`.)

- [ ] **Step 4: Smoke the scoring path end-to-end on size S**

With the proxy running, run a 1-rep CrewAI expert via the orchestrator:

```bash
.venv-bench/bin/python harness/orchestrator/full_run.py \
  --task harness/tasks/04_csv_expert.yaml --variant S --n 1 \
  --session-id t4smoke --out-dir /tmp/t4smoke --frameworks crewai
.venv-bench/bin/python -c "import json,glob; f=glob.glob('/tmp/t4smoke/raw/crewai/*.json')[0]; d=json.load(open(f)); print('judge_score:', d['success'].get('judge_score')); print('correct:', d['extras'].get('correct'))"
```
Expected: a `judge_score` between 0 and 1 and an integer `correct` count.

- [ ] **Step 5: Commit**

```bash
git add harness/orchestrator/full_run.py
git commit -m "feat(orchestrator): score dataset_qa runs + per-variant ground truth"
```

---

## Task 12: Run the killer-demo MVP + capture the report

**Files:** none (produces results/)

- [ ] **Step 1: Run naive across sizes (CrewAI + Colmena), N=3 (N=1 for L)**

With proxy managed by run_task.sh. Run S and M at N=3:

```bash
bash scripts/run_task.sh 04_csv_naive --n 3 --frameworks "crewai colmena"
```

(`run_task.sh` resolves `04_csv_naive` via the glob `harness/tasks/04_csv_naive*.yaml`. It runs variant `default` by default — extend run_task.sh to accept `--variant`, defaulting to `S`, and pass it to full_run.py. Run once per size: `--variant S`, `--variant M`, `--variant L`.)

- [ ] **Step 2: Run expert across sizes (CrewAI), N=3**

```bash
bash scripts/run_task.sh 04_csv_expert --n 3 --frameworks "crewai" --variant S
bash scripts/run_task.sh 04_csv_expert --n 3 --frameworks "crewai" --variant M
bash scripts/run_task.sh 04_csv_expert --n 3 --frameworks "crewai" --variant L
```

- [ ] **Step 3: Confirm the asymptote**

Inspect the reports: naive `tokens_input` should grow ~10× S→M and break/overflow at L (success.ok=false, error recorded); expert `tokens_input` should stay roughly flat across S/M/L. Confirm naive-L records the failure mode rather than crashing the orchestrator.

- [ ] **Step 4: Commit the aggregated results + reports**

```bash
git add results/  # raw is gitignored; aggregated + report.md are kept
git commit -m "results(task4): naive vs expert asymptote — first killer-demo data"
```

---

## Self-Review notes

- **Spec coverage:** measurement unit (Tasks 6,8-10), naive (8,10), expert (9), deferred scoring (4,11), scorer rules (4), two task YAMLs + dataset_qa (1,6), bench_common helpers (2,3,5,7), MVP scope CrewAI naive+expert + Colmena naive (8,9,10), naive-L break handling (11 `_maybe_score_dataset_qa` error path + 12), cost/N (12). Charts/XL/other frameworks explicitly deferred (spec non-goals).
- **Type consistency:** `score_answers(answers, truth, questions) -> {per_question, correct, total, success_rate}` used identically in Tasks 4 and 11. `variant_params(task, variant)` defined in 5, used in 8/9/10. `extract_answer_dict`, `read_csv_text`, `load_orders_sqlite`, `build_questions_block` defined in 2/3/7, used in 8/9/10. Colmena handler takes `caller` (the `ColmenaCaller` from the existing llm.py), matching the Task 1 colmena handler.
- **Open dependency:** `run_task.sh` needs a `--variant` flag (Task 12 Step 1 note). Add it when first needed.

## Risks
| Risk | Mitigation |
|---|---|
| CrewAI expert agent loops/doesn't emit clean JSON | `extract_answer_dict` is tolerant; prompt demands JSON-only; cap tool output rows |
| naive-L overflows context | expected — caught by runner try/except, scored ok=false with reason (Task 11) |
| SQLite all-TEXT columns break math | prompt instructs CAST; scorer tolerates string-form numbers |
| Token correlation for colmena (no header) | reuse the session-ordered approach already in full_run.py |
