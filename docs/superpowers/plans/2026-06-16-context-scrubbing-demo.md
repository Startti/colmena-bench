# Hero Demo #1 — "The Context Tax" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, across all 6 frameworks, the cumulative input-token (and USD + LOC) divergence of a fixed 10-turn multi-turn conversation that exercises Colmena's ephemeral `load_attachment` and always-on binary tool-result scrubbing.

**Architecture:** Shared scenario assets (fixed report doc, 10-turn script, deterministic base64-chart tool) live in `bench_common/scenario05.py` so every runner uses provably identical content. Each runner gets a `task05.py` handler that runs the conversation through its native memory, returning per-turn answers + per-turn boundary timestamps. A dedicated demo orchestrator (`harness/orchestrator/demo05_run.py`) buckets proxy spans into turns by timestamp, builds the cumulative-tokens-per-turn series, computes USD + a LOC table, and writes the asymptote report. `full_run.py` (single-shot tasks) is left untouched.

**Tech Stack:** Python 3.11 per-framework venvs, LiteLLM proxy (provider-authoritative tokens via `proxy/spans/`), Colmena `run_dag` (PyO3), pytest.

**Prerequisites (already done this session):** Colmena binding rebuilt from `develop`; proxy starts via `proxy/start_proxy.sh` (reads `.env`, ignores `COLMENA_DATABASE_URL`); `.env` has `COLMENA_DATABASE_URL` + `SECURE_VALUES_KEY`. See `docs/superpowers/specs/2026-06-16-context-scrubbing-demo-design.md`.

**Reference patterns (read before starting):**
- Runner core + handler contract: `runners/_bench_common/bench_common/core.py`
- A tool handler: `runners/crewai/runner/tasks/task04_expert.py`
- Colmena LLM factory + DAG smoke: `runners/colmena/runner/llm.py`, `scripts/_dag_smoke.py`
- Orchestrator span enrichment: `harness/orchestrator/full_run.py:131-158`
- Colmena attachment mechanics: `/Users/danielgarcia/startti/colmena/docs/developer_guide/31_load_attachment.md`

---

## Task 1: Shared scenario assets (`bench_common/scenario05.py`)

**Files:**
- Create: `runners/_bench_common/bench_common/scenario05.py`
- Modify: `runners/_bench_common/bench_common/__init__.py`
- Test: `runners/_bench_common/tests/test_scenario05.py`

- [ ] **Step 1: Write the failing test**

```python
# runners/_bench_common/tests/test_scenario05.py
from bench_common import scenario05 as s


def test_report_is_substantial_text():
    assert isinstance(s.REPORT_TEXT, str)
    # ~12-15 "pages" of prose → at least ~12k chars so it dominates the asymptote.
    assert len(s.REPORT_TEXT) >= 12_000


def test_turn_script_is_ten_typed_turns():
    assert len(s.TURNS) == 10
    types = {t["type"] for t in s.TURNS}
    assert types == {"doc", "chart", "follow_up"}
    assert sum(t["type"] == "doc" for t in s.TURNS) == 4
    assert sum(t["type"] == "chart" for t in s.TURNS) == 3
    assert sum(t["type"] == "follow_up" for t in s.TURNS) == 3
    for t in s.TURNS:
        assert t["message"].strip()


def test_generate_chart_returns_fixed_data_uri():
    a = s.generate_chart("bar chart of revenue")
    b = s.generate_chart("completely different request")
    assert a == b  # deterministic: same blob regardless of input
    assert a.startswith("data:image/png;base64,")
    # Big enough that retaining it across turns is clearly visible (>= ~15KB).
    assert len(a) >= 15_000


def test_report_filename_and_doc_id():
    assert s.REPORT_DOC_ID and isinstance(s.REPORT_DOC_ID, str)
    assert s.REPORT_FILENAME.endswith((".md", ".txt"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd runners/_bench_common && PYTHONPATH=. python -m pytest tests/test_scenario05.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench_common.scenario05'`

- [ ] **Step 3: Write the implementation**

```python
# runners/_bench_common/bench_common/scenario05.py
"""Shared, deterministic assets for Hero Demo #1 (context-tax asymptote).

Every runner imports these so the document, the 10-turn script, and the chart
tool's output are provably identical across all 6 frameworks. See
docs/superpowers/specs/2026-06-16-context-scrubbing-demo-design.md.
"""
from __future__ import annotations

import base64

REPORT_DOC_ID = "q3_report"
REPORT_FILENAME = "Q3_2026_report.md"

# A fixed synthetic quarterly report. Long enough (~12-15 "pages") that carrying
# it in history every turn dominates the token asymptote. Content is invented
# and internally consistent so doc questions have real answers.
_REGIONS = [
    ("North America", 4200, 3800, 11),
    ("Europe", 3100, 2900, 7),
    ("Latin America", 1800, 1300, 38),
    ("Asia Pacific", 2600, 2100, 24),
    ("Middle East & Africa", 900, 720, 25),
]
_MONTHS = [
    ("January", 3400), ("February", 3550), ("March", 3720),
    ("April", 3810), ("May", 3990), ("June", 4150),
]
_RISKS = [
    ("Supply chain concentration", "High",
     "62% of components sourced from a single region; a disruption would stall fulfilment."),
    ("FX exposure in Latin America", "Medium",
     "Revenue booked in volatile local currencies without full hedging."),
    ("Customer concentration", "Medium",
     "Top 3 accounts represent 28% of ARR; churn of any one materially dents revenue."),
    ("Talent attrition in engineering", "Low",
     "Voluntary attrition rose to 14% annualised, above the 10% target."),
]


def _build_report() -> str:
    lines: list[str] = []
    lines.append("# Q3 2026 Business Review — Acme Analytics, Inc.\n")
    lines.append(
        "This confidential quarterly review summarises revenue performance by "
        "region, the monthly demand trend, the principal risks facing the "
        "business, and management's outlook for Q4 2026. All figures are in "
        "thousands of USD unless stated otherwise.\n"
    )
    lines.append("## 1. Executive summary\n")
    total_rev = sum(r[1] for r in _REGIONS)
    total_prev = sum(r[2] for r in _REGIONS)
    growth = (total_rev - total_prev) / total_prev * 100
    lines.append(
        f"Total revenue for Q3 2026 was ${total_rev:,}k, up from ${total_prev:,}k "
        f"in Q2 2026 — a quarter-over-quarter growth rate of {growth:.1f}%. Growth "
        "was led by Latin America and Asia Pacific, while North America remained "
        "the largest absolute contributor. Management views the trend as positive "
        "but flags supply-chain concentration as the dominant risk.\n"
    )
    lines.append("## 2. Revenue by region\n")
    lines.append("| Region | Q3 2026 | Q2 2026 | QoQ growth % |")
    lines.append("|---|--:|--:|--:|")
    for name, cur, prev, g in _REGIONS:
        lines.append(f"| {name} | {cur} | {prev} | {g}% |")
    lines.append("")
    for name, cur, prev, g in _REGIONS:
        lines.append(
            f"### {name}\n{name} posted ${cur:,}k in Q3 2026 versus ${prev:,}k in "
            f"Q2 2026, a growth of {g}%. " + (
                "This was the fastest-growing region in the period, driven by new "
                "logo acquisition and expansion within existing accounts. "
                if g >= 24 else
                "Performance was steady, reflecting a mature market with stable "
                "renewal rates and modest expansion. "
            ) + "Regional management expects this trajectory to continue into Q4, "
            "subject to the macro conditions described in Section 5.\n"
        )
    lines.append("## 3. Monthly demand trend\n")
    lines.append("| Month | Bookings |")
    lines.append("|---|--:|")
    for mname, val in _MONTHS:
        lines.append(f"| {mname} | {val} |")
    lines.append("")
    lines.append(
        "Monthly bookings rose every month of the quarter, from "
        f"{_MONTHS[0][1]} in {_MONTHS[0][0]} to {_MONTHS[-1][1]} in "
        f"{_MONTHS[-1][0]}, an unbroken upward trend that management reads as "
        "evidence of strengthening demand rather than seasonal noise.\n"
    )
    lines.append("## 4. Principal risks\n")
    for i, (title, sev, detail) in enumerate(_RISKS, 1):
        lines.append(f"### 4.{i} {title} (severity: {sev})\n{detail}\n")
    lines.append("## 5. Outlook and macro context\n")
    # Pad with substantive, varied prose so the doc reaches ~12-15 pages without
    # being filler the model can't reason about.
    for name, cur, prev, g in _REGIONS:
        lines.append(
            f"For {name}, the Q4 plan assumes continued {g}% momentum, partially "
            "offset by tougher comparables. The pipeline coverage ratio stands at "
            "3.1x, above the 3.0x threshold management considers healthy. Sales "
            "cycles lengthened slightly versus Q2, which the revenue operations "
            "team attributes to increased procurement scrutiny among enterprise "
            "buyers. Mitigations include earlier multi-threading and tighter "
            "qualification at the top of funnel.\n"
        )
    lines.append("## 6. Methodology and definitions\n")
    lines.append(
        "Revenue is recognised on delivery in accordance with the company's "
        "standard policy. 'Bookings' denotes the total contract value signed in "
        "the month. 'QoQ growth' compares Q3 2026 to Q2 2026. Regional figures "
        "are allocated by customer billing address. This report is unaudited and "
        "intended for internal management review only.\n"
    )
    return "\n".join(lines)


REPORT_TEXT = _build_report()

# Ground-truth facts derived from the report, for the light quality guardrail.
_TOTAL_REV = sum(r[1] for r in _REGIONS)
QUALITY_CHECKS = {
    # turn index (0-based) -> list of substrings that a correct answer should contain
    0: ["positive"],                      # key findings mention positive trend
    1: ["North America"],                 # highest revenue region
    7: ["Supply chain"],                  # top risk
}

TURNS = [
    {"type": "doc", "message": "Summarize the key findings of the attached report."},
    {"type": "doc", "message": "Which region had the highest revenue in Q3 2026?"},
    {"type": "chart", "message": "Generate a bar chart of revenue by region."},
    {"type": "doc", "message": "What was the quarter-over-quarter revenue growth rate?"},
    {"type": "follow_up", "message": "Based on that, is the overall trend positive?"},
    {"type": "chart", "message": "Generate a line chart of the monthly bookings trend."},
    {"type": "follow_up", "message": "In one sentence, what do the two charts together show?"},
    {"type": "doc", "message": "What were the top 3 risks listed in the report?"},
    {"type": "chart", "message": "Generate a chart of risk severity."},
    {"type": "follow_up", "message": "Give a short executive summary of this whole conversation."},
]

# A fixed, opaque PNG payload. We do NOT render a real chart — determinism and a
# stable size matter more than the pixels, and the LLM never needs to read it.
# ~24KB of bytes → ~32KB base64. Same blob for every call (input ignored).
_CHART_BYTES = (b"\x89PNG\r\n\x1a\n" + b"COLMENA_BENCH_FIXED_CHART_PAYLOAD_" * 720)
_CHART_DATA_URI = "data:image/png;base64," + base64.b64encode(_CHART_BYTES).decode("ascii")


def generate_chart(description: str) -> str:  # noqa: ARG001 — input intentionally ignored
    """Return a fixed base64 PNG data URI. Deterministic regardless of input.

    This simulates a chart-generation tool whose raw image output is useless in
    an LLM's text context — Colmena elides it (always-on binary scrubber), the
    other frameworks retain it in history every subsequent turn.
    """
    return _CHART_DATA_URI


CHART_TOOL_NAME = "generate_chart"
CHART_TOOL_DESCRIPTION = (
    "Generate a chart image from a natural-language description. Returns the "
    "chart as a base64 PNG data URI."
)
SYSTEM_MESSAGE = (
    "You are a report analyst assistant. Answer the user's questions about the "
    "attached Q3 2026 report. When the user asks for a chart, call the "
    f"{CHART_TOOL_NAME} tool and then confirm in one short sentence that the "
    "chart was generated — do NOT paste the image data into your reply."
)
```

- [ ] **Step 4: Export the new symbols**

In `runners/_bench_common/bench_common/__init__.py`, add (match the existing export style):

```python
from . import scenario05  # noqa: F401
from .scenario05 import (  # noqa: F401
    REPORT_TEXT, REPORT_DOC_ID, REPORT_FILENAME, TURNS, generate_chart,
    CHART_TOOL_NAME, CHART_TOOL_DESCRIPTION, SYSTEM_MESSAGE, QUALITY_CHECKS,
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd runners/_bench_common && PYTHONPATH=. python -m pytest tests/test_scenario05.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add runners/_bench_common/bench_common/scenario05.py runners/_bench_common/bench_common/__init__.py runners/_bench_common/tests/test_scenario05.py
git commit -m "feat(demo05): shared scenario assets (report doc, 10-turn script, fixed chart tool)"
```

---

## Task 2: Handler protocol carries per-turn extras (core.py)

The current handler returns `(answer, usage)`. Multi-turn runners must also emit per-turn boundary timestamps so the orchestrator can bucket spans by turn. Extend `run()` to accept an optional 3rd return element (extras) and pass it to `emit_output`. Backward compatible: 2-tuples still work.

**Files:**
- Modify: `runners/_bench_common/bench_common/core.py:155-202` (`run`), and `emit_output` already accepts `extras`.
- Test: `runners/_bench_common/tests/test_core_extras.py`

- [ ] **Step 1: Write the failing test**

```python
# runners/_bench_common/tests/test_core_extras.py
import json
import sys
from pathlib import Path

from bench_common import core


def _args(tmp_path: Path) -> core.RunnerArgs:
    task = tmp_path / "t.yaml"
    task.write_text(
        'id: "demo"\nsuccess:\n  kind: regex\n  pattern: "."\n'
    )
    return core.RunnerArgs(
        task=task, variant="default", run_id="r1", model_alias="gemini-2.5-flash",
        proxy_base_url="http://x", output=tmp_path / "o.json", timeout_seconds=10,
    )


def test_run_threads_handler_extras_into_output(tmp_path, monkeypatch):
    args = _args(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "runner", "--task", str(args.task), "--variant", "default",
        "--run-id", "r1", "--model-alias", "gemini-2.5-flash",
        "--proxy-base-url", "http://x", "--output", str(args.output),
        "--timeout-seconds", "10",
    ])

    def handler(task, llm, a):
        return "ok", {"input": 1, "output": 1, "cached": 0, "tool_calls": 0}, {"turn_boundaries": ["t0", "t1"]}

    core.run("fw", lambda: "1.0", lambda a: None, {"demo": handler})
    out = json.loads(args.output.read_text())
    assert out["extras"]["turn_boundaries"] == ["t0", "t1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd runners/_bench_common && PYTHONPATH=. python -m pytest tests/test_core_extras.py -v`
Expected: FAIL — extras not threaded (KeyError / empty extras)

- [ ] **Step 3: Modify `run()` to accept an optional extras element**

In `core.py`, replace the handler-call block (currently `answer, usage = handlers[task_id](task, llm, args)`) and the `emit_output(...)` call:

```python
    llm = llm_factory(args)
    started = datetime.now(timezone.utc)
    answer: Any = None
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras: dict[str, Any] = {}
    error: str | None = None
    try:
        result = handlers[task_id](task, llm, args)
        if len(result) == 3:
            answer, usage, extras = result
        else:
            answer, usage = result
    except Exception as e:  # noqa: BLE001 — runner-level catch-all
        error = f"{type(e).__name__}: {e}"
    ended = datetime.now(timezone.utc)
```

And add `extras=extras,` to the `emit_output(...)` call (it already has an `extras` parameter).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd runners/_bench_common && PYTHONPATH=. python -m pytest tests/test_core_extras.py tests/ -v`
Expected: PASS (new test + existing tests still green)

- [ ] **Step 5: Commit**

```bash
git add runners/_bench_common/bench_common/core.py runners/_bench_common/tests/test_core_extras.py
git commit -m "feat(core): handlers may return per-turn extras (3-tuple), threaded to output"
```

---

## Task 3: Task definition YAML

**Files:**
- Create: `harness/tasks/05_context_scrubbing.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
# Hero Demo #1 — multi-turn "context tax". A fixed 10-turn conversation over an
# attached report + a base64-chart tool. Measures cumulative input tokens/turn:
# Colmena stays flat (ephemeral attachment + binary scrubbing); the others grow.
# See docs/superpowers/specs/2026-06-16-context-scrubbing-demo-design.md.
id: "05_context_scrubbing"
title: "Context tax — multi-turn attachment + tool-output scrubbing"
version: "0.1.0"
description: >
  A 10-turn report-assistant conversation. The runner replays a fixed script of
  user messages (defined in bench_common.scenario05), keeping each framework's
  native conversation memory, with one base64-returning chart tool and one
  attached report document.
variants:
  - name: default
prompt: ""   # the conversation script lives in bench_common.scenario05.TURNS
tools: [generate_chart]
metrics: [tokens_input_per_turn, cost_usd, lines_of_code]
success:
  kind: multi_turn_demo   # scored by demo05_run.py, not the runner
model_alias: gemini-2.5-flash
timeout_seconds: 300
n_runs: 1
```

- [ ] **Step 2: Verify it parses**

Run: `cd /Users/danielgarcia/startti/colmena-bench && python -c "import yaml; print(yaml.safe_load(open('harness/tasks/05_context_scrubbing.yaml'))['id'])"`
Expected: `05_context_scrubbing`

- [ ] **Step 3: Commit**

```bash
git add harness/tasks/05_context_scrubbing.yaml
git commit -m "feat(demo05): task definition YAML"
```

---

## Task 4: Span→turn bucketing helper

A pure function that, given proxy spans (each with `ts_start`, `tokens_input`, `tokens_output`) and turn-boundary timestamps (ISO strings, length = n_turns + 1), returns a per-turn list of summed input/output tokens, plus the cumulative input series.

**Files:**
- Create: `harness/orchestrator/demo05_buckets.py`
- Test: `harness/orchestrator/tests/test_demo05_buckets.py`

- [ ] **Step 1: Write the failing test**

```python
# harness/orchestrator/tests/test_demo05_buckets.py
from datetime import datetime, timezone

from demo05_buckets import bucket_spans_by_turn, _to_epoch


def _iso(sec: int) -> str:
    return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def test_buckets_spans_into_turns_and_cumulates():
    # boundaries at t=0,10,20,30 → 3 turns: [0,10), [10,20), [20,30)
    boundaries = [_iso(0), _iso(10), _iso(20), _iso(30)]
    spans = [
        {"ts_start": _to_epoch(_iso(1)), "tokens_input": 100, "tokens_output": 5},
        {"ts_start": _to_epoch(_iso(2)), "tokens_input": 50, "tokens_output": 5},   # turn 0
        {"ts_start": _to_epoch(_iso(12)), "tokens_input": 200, "tokens_output": 9}, # turn 1
        {"ts_start": _to_epoch(_iso(25)), "tokens_input": 400, "tokens_output": 9}, # turn 2
    ]
    res = bucket_spans_by_turn(spans, boundaries)
    assert res["per_turn_input"] == [150, 200, 400]
    assert res["cumulative_input"] == [150, 350, 750]
    assert res["per_turn_output"] == [10, 9, 9]


def test_spans_after_last_boundary_go_to_last_turn():
    boundaries = [_iso(0), _iso(10)]
    spans = [{"ts_start": _to_epoch(_iso(99)), "tokens_input": 7, "tokens_output": 1}]
    res = bucket_spans_by_turn(spans, boundaries)
    assert res["per_turn_input"] == [7]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd harness/orchestrator && PYTHONPATH=. python -m pytest tests/test_demo05_buckets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'demo05_buckets'`

- [ ] **Step 3: Write the implementation**

```python
# harness/orchestrator/demo05_buckets.py
"""Bucket proxy spans into conversation turns by wall-clock timestamp.

Colmena cannot forward a per-call header, so we attribute each span to a turn by
comparing its ts_start to the runner-emitted turn-boundary timestamps. Works
identically for every framework.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _to_epoch(ts: Any) -> float:
    """Accept an ISO-8601 string (…Z) or an epoch float; return epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).replace("Z", "+00:00")
    return datetime.fromisoformat(s).timestamp()


def bucket_spans_by_turn(spans: list[dict], boundaries: list[str]) -> dict:
    """Sum span tokens into turns delimited by `boundaries`.

    boundaries has length n_turns + 1: turn k = [boundaries[k], boundaries[k+1]).
    A span at/after the last boundary is attributed to the last turn (handles
    clock skew on the final emit).
    """
    edges = [_to_epoch(b) for b in boundaries]
    n_turns = max(0, len(edges) - 1)
    per_in = [0 for _ in range(n_turns)]
    per_out = [0 for _ in range(n_turns)]
    for sp in spans:
        t = _to_epoch(sp.get("ts_start", 0))
        idx = 0
        while idx < n_turns - 1 and t >= edges[idx + 1]:
            idx += 1
        per_in[idx] += int(sp.get("tokens_input", 0))
        per_out[idx] += int(sp.get("tokens_output", 0))
    cum, running = [], 0
    for v in per_in:
        running += v
        cum.append(running)
    return {
        "per_turn_input": per_in,
        "per_turn_output": per_out,
        "cumulative_input": cum,
    }
```

- [ ] **Step 4: Create the tests dir init + run**

```bash
mkdir -p harness/orchestrator/tests && touch harness/orchestrator/tests/__init__.py
cd harness/orchestrator && PYTHONPATH=. python -m pytest tests/test_demo05_buckets.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add harness/orchestrator/demo05_buckets.py harness/orchestrator/tests/
git commit -m "feat(demo05): span→turn bucketing by timestamp + tests"
```

---

## Task 5: LOC counter helper

Counts non-blank, non-comment Python (and JSON) lines of a runner's `task05` handler — the node-vs-code metric. JSON DAG files count every non-blank line.

**Files:**
- Create: `harness/orchestrator/demo05_loc.py`
- Test: `harness/orchestrator/tests/test_demo05_loc.py`

- [ ] **Step 1: Write the failing test**

```python
# harness/orchestrator/tests/test_demo05_loc.py
from demo05_loc import count_loc


def test_counts_code_lines_ignores_blank_and_comments(tmp_path):
    p = tmp_path / "h.py"
    p.write_text(
        "# a comment\n"
        "\n"
        "import os\n"
        "x = 1  # trailing\n"
        "    # indented comment\n"
        "y = 2\n"
    )
    assert count_loc(p) == 3  # import os / x = 1 / y = 2


def test_json_counts_nonblank_lines(tmp_path):
    p = tmp_path / "dag.json"
    p.write_text('{\n  "a": 1,\n\n  "b": 2\n}\n')
    assert count_loc(p) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd harness/orchestrator && PYTHONPATH=. python -m pytest tests/test_demo05_loc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'demo05_loc'`

- [ ] **Step 3: Write the implementation**

```python
# harness/orchestrator/demo05_loc.py
"""Lines-of-code counter for the node-vs-code metric (Hero Demo #1).

Counts non-blank, non-comment-only lines. For .py, a line whose first
non-whitespace char is '#' is a comment. For .json (Colmena DAG), every
non-blank line counts.
"""
from __future__ import annotations

from pathlib import Path


def count_loc(path: Path) -> int:
    text = Path(path).read_text()
    is_py = str(path).endswith(".py")
    n = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if is_py and line.startswith("#"):
            continue
        n += 1
    return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd harness/orchestrator && PYTHONPATH=. python -m pytest tests/test_demo05_loc.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add harness/orchestrator/demo05_loc.py harness/orchestrator/tests/test_demo05_loc.py
git commit -m "feat(demo05): LOC counter for node-vs-code metric + tests"
```

---

## Task 6: Colmena `task05` handler (DAG with attachment + base64 chart tool)

Colmena runs the conversation as a sequence of `run_dag` calls sharing one stable `agent_session_id` (so attachment catalog + history persist). Turn 1 attaches the report via `files[]`; later turns reuse the catalog. A `python_script` (or `http_request`) tool node returns the base64 chart — but the simplest deterministic path is a single `llm_call` node per turn whose config enables a chart tool. We use a `python_script` tool that returns the fixed data URI; Colmena's scrubber elides it.

**Files:**
- Create: `runners/colmena/runner/tasks/task05.py`
- Create: `runners/colmena/dags/demo05_turn.json` (a one-`llm_call`-node DAG template)
- Modify: `runners/colmena/runner/__init__.py` (register the `05_context_scrubbing` handler)
- Smoke: `scripts/smoke_demo05_colmena.sh`

- [ ] **Step 1: Read the attachment + tool docs and an example graph**

Read `/Users/danielgarcia/startti/colmena/docs/developer_guide/31_load_attachment.md` (catalog + ephemeral semantics) and `/Users/danielgarcia/startti/colmena/tests/graphs/agents/load_attachment_basic.json`. Confirm the `llm_call` config fields: `provider`, `model`, `api_key`, `connection_url` (`${DATABASE_URL}`), `agent_session_id`/`session_id`, `attachments_enabled`, `system_message`, `prompt`, `files[]`, and `tool_configurations` for a custom tool. Verify a `python_script` tool node can return a fixed string.

- [ ] **Step 2: Write the DAG template**

```json
// runners/colmena/dags/demo05_turn.json
{
  "nodes": {
    "ask": {
      "type": "llm_call",
      "config": {
        "provider": "openai",
        "model": "${MODEL_ALIAS}",
        "api_key": "${OPENAI_API_KEY}",
        "connection_url": "${DATABASE_URL}",
        "attachments_enabled": true,
        "system_message": "${SYSTEM_MESSAGE}",
        "prompt": "${PROMPT}",
        "tool_configurations": {
          "generate_chart": {
            "name": "generate_chart",
            "node_type": "python_script",
            "description": "Generate a chart image from a description. Returns a base64 PNG data URI.",
            "node_schema": {
              "code": { "fixed": "result = '${CHART_DATA_URI}'" }
            }
          }
        }
      }
    },
    "out": { "type": "log" }
  },
  "edges": [{ "from": "ask", "to": "out" }]
}
```

> NOTE: confirm the exact `python_script` tool shape during Step 1 against the
> installed Colmena (`reg.toolkit_catalog`/example graphs). If a fixed-output
> tool is awkward as `python_script`, use an `http_request` tool pointed at a
> tiny local echo, or inject the chart via the prompt path. The contract that
> matters: a tool whose result is a >15KB base64 data URI so the scrubber elides
> it. Adjust the template, keep the handler's call sequence.

- [ ] **Step 3: Write the handler**

```python
# runners/colmena/runner/tasks/task05.py
"""Task 5 (context tax) — Colmena: one run_dag per turn, shared agent session.

Turn 1 attaches the report via files[]; subsequent turns reuse the session's
attachment catalog (load_attachment is ephemeral) and persisted history. The
chart tool returns a base64 data URI that Colmena's always-on scrubber elides
from history. Per-turn boundary timestamps let the orchestrator bucket spans.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench_common import (
    RunnerArgs, REPORT_TEXT, REPORT_DOC_ID, REPORT_FILENAME, TURNS,
    SYSTEM_MESSAGE, generate_chart,
)

RUNNER_DIR = Path(__file__).resolve().parents[1]
DAG_TEMPLATE = (RUNNER_DIR / "dags" / "demo05_turn.json").read_text()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(task_def: dict[str, Any], caller: Any, args: RunnerArgs) -> tuple[Any, dict[str, int], dict]:
    # Engine needs the Postgres DB (proxy-safe alias) + secure-value key.
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    import colmena

    session = f"demo05_{args.run_id}"
    chart_uri = generate_chart("")
    answers: list[str] = []
    boundaries: list[str] = [_now_iso()]

    for i, turn in enumerate(TURNS):
        dag = json.loads(
            DAG_TEMPLATE
            .replace("${MODEL_ALIAS}", args.model_alias)
            .replace("${SYSTEM_MESSAGE}", json.dumps(SYSTEM_MESSAGE)[1:-1])
            .replace("${PROMPT}", json.dumps(turn["message"])[1:-1])
            .replace("${CHART_DATA_URI}", chart_uri)
        )
        # Attach the report only on turn 1; the catalog persists by session.
        if i == 0:
            dag["nodes"]["ask"]["config"]["files"] = [{
                "id": REPORT_DOC_ID,
                "filename": REPORT_FILENAME,
                "mime_type": "text/markdown",
                "label": "Q3 2026 report",
                "data": REPORT_TEXT,  # inline text content
            }]
        out = colmena.run_dag(json.dumps(dag), None, None, None, True, session)
        d = json.loads(out)
        ask = d.get("ask", {})
        answers.append(str(ask.get("result", ask)))
        boundaries.append(_now_iso())

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {"turn_boundaries": boundaries, "turn_types": [t["type"] for t in TURNS]}
    return answers, usage, extras
```

> NOTE: confirm the inline-text attachment field name during Step 1. The docs
> show `files[].data` (base64/inline), `url`, or `path`. If inline text must be
> base64, encode `REPORT_TEXT` and set the right `mime_type`/encoding per the
> installed API. The smoke (Step 5) is the gate.

- [ ] **Step 4: Register the handler**

In `runners/colmena/runner/__init__.py`, import `task05` and add `"05_context_scrubbing": task05.run` to the HANDLERS dict (follow how `task04_naive` is registered).

- [ ] **Step 5: Write + run the smoke**

```bash
# scripts/smoke_demo05_colmena.sh
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
export OPENAI_API_KEY="$LITELLM_MASTER_KEY"
export OPENAI_BASE_URL="http://127.0.0.1:4000/v1"
RID="smoke05colmena"
# proxy must be running with BENCH_RUN_ID=$RID:
#   PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=$RID ./proxy/start_proxy.sh &
PYTHONPATH="runners/colmena:runners/_bench_common" \
  runners/colmena/.venv/bin/python -m runner \
  --task harness/tasks/05_context_scrubbing.yaml --variant default \
  --run-id "$RID" --model-alias gemini-2.5-flash \
  --proxy-base-url http://127.0.0.1:4000 \
  --output /tmp/demo05_colmena.json --timeout-seconds 300
python -c "import json; d=json.load(open('/tmp/demo05_colmena.json')); \
  assert len(d['answer'])==10, d['answer']; \
  assert len(d['extras']['turn_boundaries'])==11; \
  print('OK turns=', len(d['answer']))"
```

Run it (with the proxy up as noted). Expected: `OK turns= 10`, and `proxy/spans/run-smoke05colmena.jsonl` contains multiple spans whose total grows across turns (chart turns elide the base64).

- [ ] **Step 6: Commit**

```bash
git add runners/colmena/runner/tasks/task05.py runners/colmena/dags/demo05_turn.json runners/colmena/runner/__init__.py scripts/smoke_demo05_colmena.sh
git commit -m "feat(demo05): Colmena task05 handler (per-turn run_dag, attachment + chart tool)"
```

---

## Task 7: CrewAI `task05` handler (multi-turn memory + base64 tool)

CrewAI's idiomatic multi-turn: maintain a running message history and re-send it each turn. The report goes into the first user message; the chart tool returns the base64 data URI, which CrewAI keeps in history.

**Files:**
- Create: `runners/crewai/runner/tasks/task05.py`
- Modify: `runners/crewai/runner/__init__.py`
- Smoke: reuse `scripts/smoke_demo05_colmena.sh` pattern with `runners/crewai`.

- [ ] **Step 1: Inspect CrewAI's conversation/memory + tool API**

Confirm against the installed CrewAI version (`runners/crewai/.venv`) how to do a multi-turn chat that retains tool outputs. The simplest idiomatic, framework-faithful approach that also keeps full history: drive the proxy via the same `LLM` object using a manually-maintained `messages` list and CrewAI's tool calling, OR use `crewai` `Agent` with `memory=True` across `kickoff` calls. Pick the path that (a) re-sends prior turns and (b) retains the base64 tool result. Document the choice in a module docstring.

- [ ] **Step 2: Write the handler (manual message-history variant — most transparent)**

```python
# runners/crewai/runner/tasks/task05.py
"""Task 5 (context tax) — CrewAI: idiomatic multi-turn chat, full history resent.

Default behavior: the report sits in the first user message and the running
message list (including base64 chart tool results) is re-sent every turn. This
is the out-of-the-box pattern; no manual trimming/scrubbing (that's the point).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bench_common import (
    RunnerArgs, REPORT_TEXT, TURNS, SYSTEM_MESSAGE, generate_chart,
    CHART_TOOL_NAME, CHART_TOOL_DESCRIPTION,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(task_def: dict[str, Any], llm: Any, args: RunnerArgs) -> tuple[Any, dict[str, int], dict]:
    # `llm` is a crewai.LLM pointed at the proxy (see runner/llm.py). We use its
    # OpenAI-compatible call surface with a manually maintained history so the
    # token growth is the framework's default "keep everything" memory.
    from crewai import LLM  # noqa: F401  (type ref / ensures dep present)

    tools = [{
        "type": "function",
        "function": {
            "name": CHART_TOOL_NAME,
            "description": CHART_TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {"description": {"type": "string"}},
                "required": ["description"],
            },
        },
    }]

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": f"Here is the report to use for this conversation:\n\n{REPORT_TEXT}"},
        {"role": "assistant", "content": "Understood. I have the report and will answer your questions."},
    ]
    answers: list[str] = []
    boundaries: list[str] = [_now_iso()]

    for turn in TURNS:
        messages.append({"role": "user", "content": turn["message"]})
        # First completion (may request the tool).
        resp = llm.call(messages, tools=tools)  # adapt to the installed call signature
        msg = _assistant_message(resp)
        messages.append(msg)
        # If a tool was called, execute it and feed the (base64) result back —
        # which then stays in history (the default, un-scrubbed behavior).
        for tc in msg.get("tool_calls") or []:
            if tc["function"]["name"] == CHART_TOOL_NAME:
                result = generate_chart("")
                messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "name": CHART_TOOL_NAME, "content": result,
                })
        if msg.get("tool_calls"):
            resp2 = llm.call(messages, tools=tools)
            msg2 = _assistant_message(resp2)
            messages.append(msg2)
            answers.append(msg2.get("content") or "")
        else:
            answers.append(msg.get("content") or "")
        boundaries.append(_now_iso())

    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
    extras = {"turn_boundaries": boundaries, "turn_types": [t["type"] for t in TURNS]}
    return answers, usage, extras


def _assistant_message(resp: Any) -> dict:
    """Normalize the framework's completion response to an OpenAI-style message dict."""
    # Adapt to the installed CrewAI/LiteLLM return shape during Step 1; for a
    # litellm ModelResponse: resp.choices[0].message → {role, content, tool_calls}.
    choice = resp.choices[0].message
    out: dict = {"role": "assistant", "content": getattr(choice, "content", None)}
    tcs = getattr(choice, "tool_calls", None)
    if tcs:
        out["tool_calls"] = [{
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        } for tc in tcs]
    return out
```

> NOTE: `crewai.LLM.call`'s exact signature/return must be verified in Step 1. If
> CrewAI's `LLM` does not expose raw `messages`+`tools`, fall back to the
> `litellm` client directly (every runner venv has it) pointed at the proxy with
> `model=f"openai/{args.model_alias}"`, `base_url=args.proxy_base_url`, and
> `extra_headers={"x-bench-run-id": args.run_id}` — this is the same routing as
> `runner/llm.py` and keeps spans correlated. The contract (10 answers + 11
> boundaries + retained base64 in history) is what the smoke checks.

- [ ] **Step 3: Register the handler** in `runners/crewai/runner/__init__.py` (add `"05_context_scrubbing": task05.run`).

- [ ] **Step 4: Smoke**

Run the CrewAI runner the same way as Task 6 Step 5 (swap `colmena`→`crewai`, run-id `smoke05crew`, proxy header path applies automatically). Expected: 10 answers, 11 boundaries, and `proxy/spans/run-smoke05crew.jsonl` showing input tokens GROWING each turn (doc + accumulating base64).

- [ ] **Step 5: Commit**

```bash
git add runners/crewai/runner/tasks/task05.py runners/crewai/runner/__init__.py
git commit -m "feat(demo05): CrewAI task05 handler (idiomatic full-history multi-turn)"
```

---

## Task 8: Demo orchestrator (Colmena + CrewAI slice)

Runs the demo for a set of frameworks, buckets spans per turn, computes per-turn cumulative tokens + USD + LOC, and writes the report + a chart-data JSON. Start with `--frameworks colmena crewai` to validate the whole pipeline before the other 4 runners exist.

**Files:**
- Create: `harness/orchestrator/demo05_run.py`
- Reuse: `demo05_buckets.bucket_spans_by_turn`, `demo05_loc.count_loc`, `full_run.venv_python/_read_spans/_proxy_key/usd_per_run`, `pricing_table.json`.

- [ ] **Step 1: Write the orchestrator**

```python
# harness/orchestrator/demo05_run.py
"""Hero Demo #1 orchestrator — cumulative tokens/turn + USD + LOC across frameworks.

Each runner replays the fixed 10-turn script and emits per-turn boundary
timestamps (extras.turn_boundaries). We bucket proxy spans into turns by
timestamp, build the cumulative-input series, price it, count handler LOC, and
write report.md + chart_data.json.

Run with the proxy already up and BENCH_RUN_ID matching --session-id (so
Colmena's spans land in run-<session-id>.jsonl). Header-capable runners write
run-<run_id>.jsonl as usual.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR / "orchestrator"))
sys.path.insert(0, str(HARNESS_DIR))

from demo05_buckets import bucket_spans_by_turn  # noqa: E402
from demo05_loc import count_loc  # noqa: E402
from orchestrator.full_run import venv_python, _read_spans, _proxy_key, usd_per_run, PRICING  # noqa: E402

HEADER_CAPABLE = {"crewai", "langchain", "langgraph", "llamaindex", "google_adk"}

# Where each framework's task05 handler (+ DAG) lives, for LOC counting.
LOC_TARGETS = {
    "colmena": ["runners/colmena/runner/tasks/task05.py", "runners/colmena/dags/demo05_turn.json"],
    "crewai": ["runners/crewai/runner/tasks/task05.py"],
    "langchain": ["runners/langchain/runner/tasks/task05.py"],
    "langgraph": ["runners/langgraph/runner/tasks/task05.py"],
    "llamaindex": ["runners/llamaindex/runner/tasks/task05.py"],
    "google_adk": ["runners/google_adk/runner/tasks/task05.py"],
}


def _run_one(fw: str, task_path: Path, model_alias: str, proxy_base_url: str,
             out_dir: Path, run_id: str, timeout: int) -> dict | None:
    py = venv_python(fw)
    if not py.exists():
        print(f"  [skip] {fw}: no venv")
        return None
    fw_out = out_dir / fw
    fw_out.mkdir(parents=True, exist_ok=True)
    out_path = fw_out / f"{run_id}.json"
    env = os.environ.copy()
    env.update({
        "BENCH_RUN_ID": run_id,
        "LITELLM_PROXY_BASE_URL": proxy_base_url,
        "LITELLM_PROXY_API_KEY": _proxy_key(),
        "PYTHONPATH": f"{REPO_ROOT/'runners'/fw}:{REPO_ROOT/'runners'/'_bench_common'}",
    })
    proc = subprocess.run(
        [str(py), "-m", "runner", "--task", str(task_path), "--variant", "default",
         "--run-id", run_id, "--model-alias", model_alias,
         "--proxy-base-url", proxy_base_url, "--output", str(out_path),
         "--timeout-seconds", str(timeout)],
        env=env, capture_output=True, text=True, timeout=timeout + 30,
    )
    if proc.returncode != 0:
        out_path.with_suffix(".stderr").write_text(proc.stderr)
        print(f"  {fw}: exit {proc.returncode} (see .stderr)")
        return None
    return json.loads(out_path.read_text())


def _spans_for(fw: str, run_id: str, session_id: str, spans_dir: Path) -> list[dict]:
    name = run_id if fw in HEADER_CAPABLE else session_id
    return _read_spans(spans_dir / f"run-{name}.jsonl")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Hero demo #1 — context tax")
    p.add_argument("--task", type=Path, default=REPO_ROOT / "harness/tasks/05_context_scrubbing.yaml")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--session-id", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy" / "spans")
    p.add_argument("--frameworks", nargs="*", default=["colmena", "crewai"])
    args = p.parse_args(argv)

    import yaml
    task_def = yaml.safe_load(args.task.read_text())
    timeout = task_def.get("timeout_seconds", 300)

    results = []
    for fw in args.frameworks:
        print(f"==> {fw}")
        # Colmena reuses the session id as its run id (spans land in session file).
        run_id = args.session_id if fw not in HEADER_CAPABLE else str(uuid.uuid4())
        ro = _run_one(fw, args.task, args.model_alias, args.proxy_base_url,
                      args.out_dir / "raw", run_id, timeout)
        if not ro:
            continue
        boundaries = (ro.get("extras") or {}).get("turn_boundaries") or []
        spans = _spans_for(fw, run_id, args.session_id, args.spans_dir)
        buckets = bucket_spans_by_turn(spans, boundaries)
        total_in = sum(buckets["per_turn_input"])
        total_out = sum(buckets["per_turn_output"])
        ro_tok = {"input": total_in, "output": total_out, "cached": 0}
        usd = usd_per_run({"tokens": ro_tok}, args.model_alias)
        loc = sum(count_loc(REPO_ROOT / f) for f in LOC_TARGETS.get(fw, []) if (REPO_ROOT / f).exists())
        results.append({
            "framework": fw,
            "framework_version": ro.get("framework_version", ""),
            "per_turn_input": buckets["per_turn_input"],
            "cumulative_input": buckets["cumulative_input"],
            "total_input": total_in,
            "total_output": total_out,
            "turn10_input": buckets["per_turn_input"][-1] if buckets["per_turn_input"] else 0,
            "usd_total": usd,
            "loc": loc,
            "answers": ro.get("answer"),
        })
        print(f"  {fw}: total_in={total_in} turn10_in={results[-1]['turn10_input']} loc={loc}")

    if not results:
        print("no results")
        return 1
    out = args.out_dir / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "chart_data.json").write_text(json.dumps(results, indent=2))
    (out / "report.md").write_text(render_report(results))
    print(f"\nreport → {out/'report.md'}")
    print((out / "report.md").read_text())
    return 0


def render_report(results: list[dict]) -> str:
    results = sorted(results, key=lambda r: r["total_input"])
    lines = [
        "# Hero Demo #1 — The Context Tax (multi-turn token asymptote)",
        "",
        "Fixed 10-turn report-assistant conversation. Tokens are provider-"
        "authoritative (captured at the proxy). Lower is better.",
        "",
        "| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |",
        "|---|---|--:|--:|--:|--:|",
    ]
    for r in results:
        lines.append(
            f"| {r['framework']} | {r['framework_version']} | {r['total_input']:,} "
            f"| {r['turn10_input']:,} | ${r['usd_total']:.6f} | {r['loc']} |"
        )
    lines += ["", "## Cumulative input tokens per turn", "",
              "| turn | " + " | ".join(r["framework"] for r in results) + " |",
              "|--:|" + "|".join("--:" for _ in results) + "|"]
    n_turns = max((len(r["cumulative_input"]) for r in results), default=0)
    for t in range(n_turns):
        row = [str(t + 1)]
        for r in results:
            cum = r["cumulative_input"]
            row.append(f"{cum[t]:,}" if t < len(cum) else "")
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "_Competitors run their **default idiomatic** multi-turn memory (full "
        "history, retained tool outputs). To match Colmena they would need to "
        "add manual history trimming, attachment caching, and base64 scrubbing — "
        "extra code Colmena provides built-in (extra LOC = 0)._",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the slice (proxy up, BENCH_RUN_ID=demo05sess)**

```bash
cd /Users/danielgarcia/startti/colmena-bench
pkill -f litellm 2>/dev/null; sleep 1
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=demo05sess ./proxy/start_proxy.sh > /tmp/proxy_demo05.log 2>&1 &
# wait for :4000/health/liveliness == 200, then:
runners/colmena/.venv/bin/python harness/orchestrator/demo05_run.py \
  --session-id demo05sess --out-dir runs/demo05 --frameworks colmena crewai
```

Expected: a report table where **colmena total tok in << crewai**, crewai's cumulative series grows steeply, colmena's stays roughly flat, and `colmena loc < crewai loc`. Sanity-check: colmena chart turns should NOT spike (base64 elided); crewai chart turns should bump and stay elevated.

- [ ] **Step 3: Commit**

```bash
git add harness/orchestrator/demo05_run.py
git commit -m "feat(demo05): demo orchestrator — per-turn token asymptote + USD + LOC (colmena+crewai slice)"
```

---

## Task 9: LangChain `task05` handler

**Files:**
- Create: `runners/langchain/runner/tasks/task05.py`
- Modify: `runners/langchain/runner/__init__.py`

- [ ] **Step 1: Inspect** `runners/langchain/runner/tasks/task01.py` and `runner/llm.py` for the installed LangChain LLM wiring (proxy routing via `openai/` prefix + `x-bench-run-id` header).

- [ ] **Step 2: Implement** a multi-turn handler matching the SAME contract as Task 7: maintain a LangChain message list (`SystemMessage` + report in first `HumanMessage`), bind the `generate_chart` tool, loop `TURNS`, feed the base64 tool result back into the message list (retained — default behavior), record `turn_boundaries`. Return `(answers, usage, extras)`. Use `bench_common` shared assets. Idiomatic LangChain: `ChatOpenAI(...).bind_tools([...])` and append `ToolMessage(content=generate_chart(""), tool_call_id=...)`.

- [ ] **Step 3: Register** in `runners/langchain/runner/__init__.py`.

- [ ] **Step 4: Smoke** (run-id `smoke05lc`): assert 10 answers + 11 boundaries; confirm `run-smoke05lc.jsonl` input tokens grow per turn.

- [ ] **Step 5: Commit**

```bash
git add runners/langchain/runner/tasks/task05.py runners/langchain/runner/__init__.py
git commit -m "feat(demo05): LangChain task05 handler"
```

---

## Task 10: LangGraph `task05` handler

**Files:**
- Create: `runners/langgraph/runner/tasks/task05.py`
- Modify: `runners/langgraph/runner/__init__.py`

- [ ] **Step 1: Inspect** `runners/langgraph/runner/tasks/task01.py`. LangGraph's idiomatic multi-turn uses a `StateGraph` with a `MessagesState` and a checkpointer; the default keeps full message history (including tool results) across turns — exactly the baseline we want.

- [ ] **Step 2: Implement** the SAME contract: build a minimal graph (LLM node + tool node) with an in-memory checkpointer keyed by a thread id; invoke once per turn with the next `HumanMessage`; the `generate_chart` tool node returns the base64 data URI (retained in state). Record `turn_boundaries`; return `(answers, usage, extras)`. Reuse `bench_common` assets.

- [ ] **Step 3: Register** in `runners/langgraph/runner/__init__.py`.

- [ ] **Step 4: Smoke** (run-id `smoke05lg`): 10 answers + 11 boundaries; growing per-turn input tokens.

- [ ] **Step 5: Commit**

```bash
git add runners/langgraph/runner/tasks/task05.py runners/langgraph/runner/__init__.py
git commit -m "feat(demo05): LangGraph task05 handler"
```

---

## Task 11: LlamaIndex `task05` handler

**Files:**
- Create: `runners/llamaindex/runner/tasks/task05.py`
- Modify: `runners/llamaindex/runner/__init__.py`

- [ ] **Step 1: Inspect** `runners/llamaindex/runner/tasks/task01.py` + `runner/llm.py`. Use LlamaIndex's `ChatMemoryBuffer` / `SimpleChatEngine` or a `FunctionCallingAgent` with a chat memory that retains tool outputs — the default keeps history.

- [ ] **Step 2: Implement** the SAME contract: a chat engine/agent with the report seeded into memory (first message) + the `generate_chart` `FunctionTool` returning the base64 URI; `.chat(message)` once per turn over `TURNS`. Record `turn_boundaries`; return `(answers, usage, extras)`. Reuse `bench_common` assets.

- [ ] **Step 3: Register** in `runners/llamaindex/runner/__init__.py`.

- [ ] **Step 4: Smoke** (run-id `smoke05li`): 10 answers + 11 boundaries; growing per-turn input tokens.

- [ ] **Step 5: Commit**

```bash
git add runners/llamaindex/runner/tasks/task05.py runners/llamaindex/runner/__init__.py
git commit -m "feat(demo05): LlamaIndex task05 handler"
```

---

## Task 12: Google ADK `task05` handler

**Files:**
- Create: `runners/google_adk/runner/tasks/task05.py`
- Modify: `runners/google_adk/runner/__init__.py`

- [ ] **Step 1: Inspect** `runners/google_adk/runner/tasks/task01.py` + `runner/llm.py`. ADK uses a `Runner` + `Session` that retains conversation events (including tool/function responses) by default.

- [ ] **Step 2: Implement** the SAME contract: an ADK agent with the `generate_chart` tool (returns the base64 URI) and a session seeded with the report; send one user message per turn over `TURNS`, reusing the same session so history accumulates. Record `turn_boundaries`; return `(answers, usage, extras)`. Reuse `bench_common` assets.

- [ ] **Step 3: Register** in `runners/google_adk/runner/__init__.py`.

- [ ] **Step 4: Smoke** (run-id `smoke05adk`): 10 answers + 11 boundaries; growing per-turn input tokens.

- [ ] **Step 5: Commit**

```bash
git add runners/google_adk/runner/tasks/task05.py runners/google_adk/runner/__init__.py
git commit -m "feat(demo05): Google ADK task05 handler"
```

---

## Task 13: Full 6-framework run + final report

**Files:**
- Create: `scripts/run_demo05.sh` (proxy lifecycle + demo05_run for all 6)
- Output: `runs/demo05/report/report.md` + `chart_data.json`

- [ ] **Step 1: Write the run script**

```bash
# scripts/run_demo05.sh
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SESS="demo05_$(date +%s)"
pkill -f litellm 2>/dev/null || true; sleep 1
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID="$SESS" ./proxy/start_proxy.sh > /tmp/proxy_demo05.log 2>&1 &
for i in $(seq 1 45); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health/liveliness)" = "200" ] && break
  sleep 1
done
runners/colmena/.venv/bin/python harness/orchestrator/demo05_run.py \
  --session-id "$SESS" --out-dir runs/demo05 \
  --frameworks colmena crewai langchain langgraph llamaindex google_adk
pkill -f litellm 2>/dev/null || true
```

> NOTE: Colmena runs FIRST so its spans own the session file before any
> header-capable runner; header-capable runners write their own run-<id> files,
> so order does not actually matter, but keeping Colmena first avoids confusion.

- [ ] **Step 2: Run it**

Run: `bash scripts/run_demo05.sh`
Expected: `runs/demo05/report/report.md` with all 6 frameworks. Validate the headline: Colmena has the lowest `total tok in`, the lowest `turn-10 tok in`, a roughly-flat cumulative series, and competitive/lowest LOC. Competitors' cumulative series grow super-linearly.

- [ ] **Step 3: Sanity-check fairness**

Confirm each framework actually answered the 4 doc questions reasonably (spot-check `chart_data.json` answers vs `scenario05.QUALITY_CHECKS`) — proving Colmena's savings are not from lost answer quality. If a competitor's base64 was NOT retained (no asymptote), note it in the report (some frameworks may stringify/drop tool results) rather than hiding it.

- [ ] **Step 4: Commit**

```bash
git add scripts/run_demo05.sh runs/demo05/report/report.md runs/demo05/report/chart_data.json
git commit -m "feat(demo05): full 6-framework context-tax run + report"
```

- [ ] **Step 5: Update memory + strategy doc**

Append the demo result (headline numbers) to `docs/superpowers/specs/2026-06-11-benchmark-strategy-colmena-differentiators.md` (Demo #1 → DONE with numbers) and add/update a memory file `colmena-real-differentiators.md` with the measured asymptote. Commit.

---

## Self-review notes (for the executor)

- **Spec coverage:** mechanisms A+B (Tasks 6/7 + scenario05), all 6 frameworks (Tasks 6–12), cumulative-tokens/turn + USD + turn-10 tax + LOC + quality guardrail (Tasks 4/5/8/13), per-turn attribution by timestamp (Task 4 + extras in Task 2), default-idiomatic baseline + honesty note (Task 8 report text + Task 13 Step 3) — all present.
- **API-verification gates:** the per-framework handlers (Tasks 6, 7, 9–12) each begin with an inspect step and end with a smoke gate, because the exact multi-turn+tool API differs per installed framework version. The shared CONTRACT (10 answers + 11 boundaries + retained base64 + shared assets) is fixed; adapt the framework-specific calls to satisfy it, using each runner's existing `task01.py`/`llm.py` as the proxy-routing reference.
- **Token correlation:** header-capable runners use `x-bench-run-id` (their existing `llm.py`); Colmena uses the proxy session file via `--session-id` reused as its run id. Do NOT change `full_run.py`.
- **Risk:** if a framework drops/stringifies tool results so the base64 doesn't persist, the asymptote for that one weakens — report it honestly (Task 13 Step 3), it does not invalidate the doc-attachment half.
