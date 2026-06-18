# Demo #7 — Lazy Tool Loading (tool asymptote) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure accuracy, provider-authoritative tokens, and hard-error rate as a function of tool count (5→200) for Colmena lazy-ON vs lazy-OFF vs 5 competitors, on a needle-in-haystack task with easy/medium/hard needles, to show lazy tool loading lets you add many tools without failing or paying per-schema tokens.

**Architecture:** A framework-agnostic tool-set generator produces an identical spec (N tools + 1 deterministic needle, mixed difficulty) consumed by 7 per-framework handlers; a sweep driver runs every (config × count × difficulty × trial) cell in its own process, scores it from a per-run tool-call log + proxy spans, and aggregates to JSON/CSV + charts.

**Tech Stack:** Python 3.11 (per-framework venvs), `colmena` PyO3 `run_dag` with `lazy_tool_loading`, LiteLLM proxy (token source of truth), matplotlib, pytest.

**Spec:** `docs/superpowers/specs/2026-06-18-demo07-lazy-tool-loading-design.md`

---

## Verified facts this plan relies on

- Lazy tool loading: `llm_call` config `lazy_tool_loading: true`; per-tool `summary` (10–200 chars) + optional `eager`; engine exposes a `name+summary` catalog and a synthetic `describe_tool` (see `colmena/docs/developer_guide/29_lazy_tool_loading.md`). DAG-node tools (via `tool_configurations`) participate in the catalog using their `summary`/truncated `description`.
- Colmena `run_dag(graph, resume_id, resume_answer, inject_payload, include_extra_info, agent_session_id)`; engine env from `task04_expert.py::_ensure_env` (DATABASE_URL, SECURE_VALUES_KEY, COLMENA_LOCAL_STORAGE_DIR, OPENAI_BASE_URL, OPENAI_API_KEY).
- Runner CLI: `python -m runner --task <yaml> --variant <v> --run-id <id> --model-alias gemini-2.5-flash --proxy-base-url <url> --output <path>`; handler `run(task_def, llm_or_caller, args) -> (answer, usage[, extras])`.
- Proxy spans (provider-authoritative tokens) land in `proxy/spans/run-<run_id>.jsonl` (header-capable runners) or `run-<BENCH_RUN_ID>.jsonl` (colmena). Each span has `tokens_input`.
- Tool-calling idiom per framework already exists: `runners/<fw>/runner/tasks/task04_expert.py` (and `task06_refund.py`).

---

## File Structure

| File | Responsibility |
|---|---|
| `runners/_bench_common/bench_common/scenario_tools.py` | Generator (N tools + needle, mixed difficulty, distinguishable summaries), scoring, tool-call logging helper |
| `harness/tasks/07_tools.yaml` | Task def (`id: 07_tools`) |
| `runners/colmena/runner/tasks/task07_tools.py` | Colmena handler (DAG, lazy flag from env) |
| `runners/{crewai,langchain,langgraph,llamaindex,google_adk}/runner/tasks/task07_tools.py` | 5 competitor handlers (native tool registration) |
| `runners/<fw>/runner/__main__.py` | Register `07_tools` |
| `harness/orchestrator/demo_tools_run.py` | Sweep driver + scoring + aggregation |
| `harness/orchestrator/demo07_plots.py` | Charts (faceted by difficulty) |
| `scripts/run_demo07.sh` | Owns proxy + runs the sweep |
| `docs/demos/demo07-many-tools.md`, `demo07-replication.md` | Pitch + repro |

---

## Phase A — Generator + derisk

### Task 1: Tool-set generator + scoring

**Files:**
- Create: `runners/_bench_common/bench_common/scenario_tools.py`
- Modify: `runners/_bench_common/bench_common/__init__.py` (export)
- Test: `runners/_bench_common/tests/test_scenario_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# runners/_bench_common/tests/test_scenario_tools.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_common import scenario_tools as st  # noqa: E402

def test_count_and_needle_present():
    spec = st.generate_toolset(50, "hard", seed=3)
    assert spec["n_tools"] == 50
    assert len(spec["tools"]) == 50
    needles = [t for t in spec["tools"] if t["is_needle"]]
    assert len(needles) == 1
    assert needles[0]["name"] == spec["needle"]

def test_difficulty_param_counts():
    easy = st.generate_toolset(20, "easy", seed=1)
    hard = st.generate_toolset(20, "hard", seed=1)
    en = next(t for t in easy["tools"] if t["is_needle"])
    hn = next(t for t in hard["tools"] if t["is_needle"])
    assert 1 <= len(en["params"]) <= 2
    assert 6 <= len(hn["params"]) <= 10

def test_population_is_mixed_difficulty():
    spec = st.generate_toolset(60, "medium", seed=2)
    sizes = [len(t["params"]) for t in spec["tools"] if not t["is_needle"]]
    assert min(sizes) <= 2 and max(sizes) >= 6   # spans easy..hard

def test_summaries_distinguishable_at_200():
    spec = st.generate_toolset(200, "hard", seed=7)
    names = [t["name"] for t in spec["tools"]]
    summaries = [t["summary"] for t in spec["tools"]]
    assert len(set(names)) == 200          # no name collisions
    assert len(set(summaries)) == 200      # no summary collisions
    for s in summaries:
        assert 10 <= len(s) <= 200

def test_question_and_expected_args():
    spec = st.generate_toolset(10, "hard", seed=5)
    needle = next(t for t in spec["tools"] if t["is_needle"])
    # every required param of the needle has a value in expected_args, and the
    # question text mentions each value so the model can fill them.
    for p in needle["params"]:
        if p["required"]:
            assert p["name"] in spec["expected_args"]
            assert str(spec["expected_args"][p["name"]]) in spec["question"]

def test_needle_random_position_varies_with_seed():
    idx = lambda s: next(i for i, t in enumerate(st.generate_toolset(50, "easy", seed=s)["tools"]) if t["is_needle"])
    assert len({idx(s) for s in range(8)}) > 1   # not always the same slot

def test_score_all_correct():
    spec = st.generate_toolset(10, "easy", seed=1)
    needle = spec["needle"]
    log = [{"tool": needle, "args": spec["expected_args"]}]
    res = st.score(spec, log, final_answer=f"The answer is {spec['expected_answer']}.")
    assert res == {"selection_ok": True, "arg_ok": True, "answer_ok": True}

def test_score_wrong_tool():
    spec = st.generate_toolset(10, "easy", seed=1)
    log = [{"tool": "some_distractor", "args": {}}]
    res = st.score(spec, log, final_answer="not applicable")
    assert res["selection_ok"] is False and res["answer_ok"] is False
```

- [ ] **Step 2: Run to verify it fails** — `cd runners/_bench_common && .venv/bin/python -m pytest tests/test_scenario_tools.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement the generator**

```python
# runners/_bench_common/bench_common/scenario_tools.py
"""Demo #7 — generator for the many-tools needle-in-haystack experiment.

Produces a framework-agnostic toolset spec consumed identically by all runners:
N tools (mixed easy/medium/hard by param count) of which exactly one is the
deterministic `needle` that answers the question. Distractors are no-ops. The
generator is seeded so a given (n, difficulty, seed) is byte-stable across the
7 configs in a trial (fairness), but varies across trials.
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


def _param_count(diff: str, rng: random.Random) -> int:
    lo, hi = _DIFF_RANGE[diff]
    return rng.randint(lo, hi)


def _make_params(k: int, rng: random.Random) -> list[dict]:
    chosen = rng.sample(_PARAM_POOL, min(k, len(_PARAM_POOL)))
    params = []
    for i, (nm, ty) in enumerate(chosen):
        params.append({"name": nm, "type": ty, "required": i == 0,
                       "description": f"The {nm.replace('_', ' ')} ({ty})."})
    return params


def _value_for(p: dict, rng: random.Random) -> Any:
    return {"string": "X7", "integer": 7, "boolean": True,
            "array": ["a"]}[p["type"]]


def generate_toolset(n: int, needle_difficulty: str, seed: int) -> dict:
    rng = random.Random((n, needle_difficulty, seed).__hash__())
    # Build n unique (verb, noun, idx) tool names.
    combos = [(v, nn) for v in _VERBS for nn in _NOUNS]
    rng.shuffle(combos)
    diffs = ["easy", "medium", "hard"]
    tools: list[dict] = []
    used = set()
    i = 0
    while len(tools) < n:
        v, nn = combos[i % len(combos)]
        suffix = i // len(combos)
        name = f"{v}_{nn}" + (f"_{suffix}" if suffix else "")
        i += 1
        if name in used:
            continue
        used.add(name)
        diff = diffs[len(tools) % 3]   # mix ~1/3 each
        params = _make_params(_param_count(diff, rng), rng)
        tools.append({
            "name": name,
            "summary": f"{v.capitalize()} {_ASPECT[v]} {nn} record. Use for {nn} {v} requests.",
            "description": f"{v.capitalize()} {nn}. Parameters: " +
                           ", ".join(p["name"] for p in params) + ".",
            "params": params,
            "is_needle": False,
            "answer": "not applicable",
        })
    # Promote one tool to the needle, give it needle_difficulty params + a
    # deterministic answer keyed on its required params.
    needle_idx = rng.randrange(n)
    nt = tools[needle_idx]
    nt["params"] = _make_params(_param_count(needle_difficulty, rng), rng)
    nt["is_needle"] = True
    answer = f"{rng.randint(1000, 9999)}.00"
    nt["answer"] = answer
    expected_args = {p["name"]: _value_for(p, rng) for p in nt["params"] if p["required"]}
    # Build a question that supplies every required value so the model can fill args.
    arg_phrase = ", ".join(f"{k}={v}" for k, v in expected_args.items())
    question = (f"Use the `{nt['name']}` tool with {arg_phrase} and report the "
                f"resulting total amount in USD. Answer with just the number.")
    return {
        "n_tools": n, "needle_difficulty": needle_difficulty, "seed": seed,
        "needle": nt["name"], "expected_args": expected_args,
        "expected_answer": answer, "question": question, "tools": tools,
    }


def log_tool_call(tool_name: str, args: dict) -> None:
    """Append a tool invocation to BENCH_TOOLCALL_LOG (JSONL). No-op if unset."""
    path = os.environ.get("BENCH_TOOLCALL_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tool": tool_name, "args": args}) + "\n")


def read_tool_calls(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def score(spec: dict, tool_calls: list[dict], final_answer: str) -> dict:
    """selection_ok = needle was called; arg_ok = called with expected args;
    answer_ok = expected answer appears in the final text."""
    needle = spec["needle"]
    called = [c for c in tool_calls if c.get("tool") == needle]
    selection_ok = len(called) > 0
    arg_ok = any(
        all(str(c.get("args", {}).get(k)) == str(v) for k, v in spec["expected_args"].items())
        for c in called
    )
    answer_ok = spec["expected_answer"] in (final_answer or "")
    return {"selection_ok": selection_ok, "arg_ok": arg_ok, "answer_ok": answer_ok}
```

- [ ] **Step 4: Export** — add `from . import scenario_tools  # noqa: F401` and `"scenario_tools"` to `__all__` in `runners/_bench_common/bench_common/__init__.py` (match existing style).

- [ ] **Step 5: Run tests → all pass.**

- [ ] **Step 6: Commit**

```bash
git add runners/_bench_common/bench_common/scenario_tools.py runners/_bench_common/bench_common/__init__.py runners/_bench_common/tests/test_scenario_tools.py
git commit -m "feat(demo07): toolset generator (mixed-difficulty needle-in-haystack) + scoring"
```

---

### Task 2: Task YAML

**Files:** Create `harness/tasks/07_tools.yaml`

- [ ] **Step 1: Write it**

```yaml
# Demo #7 — many-tools needle-in-haystack (lazy tool loading).
# Scored by harness/orchestrator/demo_tools_run.py (sweep driver), not full_run.
# The toolset + question arrive via env BENCH_TOOLSET_PATH (the driver writes it).
id: "07_tools"
prompt: |
  You are an assistant with many tools. Call exactly the one tool that answers the
  user's request, with the correct arguments, then report the result.
tools: []
metrics: [accuracy, tokens, hard_error]
success:
  kind: tool_needle
model_alias: gemini-2.5-flash
timeout_seconds: 120
n_runs: 1
```

- [ ] **Step 2: Validate** — `cd /Users/danielgarcia/startti/colmena-bench && .venv-bench/bin/python -c "import yaml; print(yaml.safe_load(open('harness/tasks/07_tools.yaml'))['id'])"` → prints `07_tools`.

- [ ] **Step 3: Commit** — `git add harness/tasks/07_tools.yaml && git commit -m "feat(demo07): task YAML"`

---

### Task 3: Colmena handler (lazy flag from env)

**Files:**
- Create: `runners/colmena/runner/tasks/task07_tools.py`
- Modify: `runners/colmena/runner/__main__.py`

- [ ] **Step 1: Implement**

```python
"""Demo #7 — Colmena many-tools handler. Builds a DAG with ONE llm_call whose
tool_configurations hold the N generated tools; `lazy_tool_loading` is set from
env BENCH_COLMENA_LAZY (1/0) so the same handler drives the lazy-ON and lazy-OFF
configs. Each tool is a python_script that logs its call and returns its answer
(needle) or "not applicable" (distractor). Mirrors task04_expert env setup."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
from bench_common import RunnerArgs, scenario_tools

REPO_ROOT = Path(__file__).resolve().parents[4]

def _ensure_env(caller: Any) -> None:
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    os.environ.setdefault("SECURE_VALUES_KEY", "0" * 64)
    sd = Path("/tmp/colmena-bench-storage"); sd.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_DIR", str(sd))
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")

def _tool_code(answer: str) -> str:
    # logs the call (args are injected as globals) then returns the answer.
    log = os.environ.get("BENCH_TOOLCALL_LOG", "")
    return (
        "import json\n"
        f"_log = {json.dumps(log)}\n"
        "_args = {k: v for k, v in list(globals().items()) if not k.startswith('_') and k not in ('json',)}\n"
        "try:\n"
        f"    open(_log, 'a').write(json.dumps({{'tool': {json.dumps('__NAME__')}, 'args': _args}}) + chr(10)) if _log else None\n"
        "except Exception:\n    pass\n"
        f"output = {{'result': {json.dumps(answer)}}}\n"
    )

def _build_dag(model_alias: str, spec: dict, lazy: bool) -> dict:
    tool_cfgs = {}
    for t in spec["tools"]:
        schema = {"code": {"type": "string", "fixed": _tool_code(t["answer"]).replace("__NAME__", t["name"])},
                  "sandbox_mode": {"type": "string", "fixed": "none"}}
        for p in t["params"]:
            schema[p["name"]] = {"type": p["type"] if p["type"] != "array" else "string",
                                 "required": p["required"], "description": p["description"]}
        tool_cfgs[t["name"]] = {"name": t["name"], "summary": t["summary"][:200],
                                "description": t["description"], "node_type": "python_script",
                                "node_schema": schema}
    return {"nodes": {
        "trigger": {"type": "trigger_webhook", "config": {"path": "/tools"}},
        "assistant": {"type": "llm_call", "max_total_calls": 12, "config": {
            "provider": "openai", "model": model_alias, "api_key": "${OPENAI_API_KEY}",
            "connection_url": "${DATABASE_URL}", "temperature": 0, "stream": False,
            "lazy_tool_loading": lazy,
            "system_message": "Call exactly the one tool that answers the user's request with correct arguments, then report the result number.",
            "tool_configurations": tool_cfgs}},
        "log": {"type": "log"}},
        "edges": [{"from": "trigger", "to": "assistant"}, {"from": "assistant", "to": "log"}]}

def run(task_def: dict, caller: Any, args: RunnerArgs):
    import colmena
    _ensure_env(caller)
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    lazy = os.environ.get("BENCH_COLMENA_LAZY", "1") == "1"
    dag = _build_dag(caller.model_alias, spec, lazy)
    out = json.loads(colmena.run_dag(dag, None, None, {"prompt": spec["question"]}, True,
                                     f"tools_{args.run_id}"))
    node = out.get("assistant", {})
    text = node.get("result", node) if isinstance(node, dict) else str(node)
    return {"answer": str(text)}, {"input": 0, "output": 0, "cached": 0}, {"final": out, "lazy": lazy}
```

- [ ] **Step 2: Register** in `runners/colmena/runner/__main__.py`: add `task07_tools` import and `"07_tools": task07_tools.run`.

- [ ] **Step 3: Manual smoke (proxy up, .env sourced)**

```bash
export BENCH_TOOLSET_PATH=/tmp/ts.json BENCH_TOOLCALL_LOG=/tmp/tc.jsonl BENCH_COLMENA_LAZY=1
.venv-bench/bin/python -c "import sys; sys.path.insert(0,'runners/_bench_common'); from bench_common import scenario_tools as st, json; open('/tmp/ts.json','w').write(__import__('json').dumps(st.generate_toolset(25,'hard',1)))"
rm -f /tmp/tc.jsonl
PYTHONPATH="$PWD/runners/colmena:$PWD/runners/_bench_common" runners/colmena/.venv/bin/python -m runner --task harness/tasks/07_tools.yaml --variant n25 --run-id tools_c1 --model-alias gemini-2.5-flash --proxy-base-url http://127.0.0.1:4000 --output /tmp/tc1.json
cat /tmp/tc.jsonl   # should show the needle called with args
```
Expected: the needle tool appears in `/tmp/tc.jsonl`; `/tmp/tc1.json` answer contains the expected number. Iterate DAG config until the lazy tool loop fires (check proxy log for `describe_tool`).

- [ ] **Step 4: Commit** — `git add runners/colmena/runner/tasks/task07_tools.py runners/colmena/runner/__main__.py && git commit -m "feat(demo07): colmena many-tools handler (lazy flag from env)"`

---

### Task 4: DERISK — lazy ON vs OFF + competitor 200-tool probe

**Files:** none committed except a one-line findings note appended to the spec §9.

- [ ] **Step 1: Run colmena lazy ON vs OFF at n=100 and n=200** (proxy up, audit not needed). For each of lazy=1 and lazy=0, generate a toolset, run the colmena handler, and record from `proxy/spans/run-<run_id>.jsonl` the summed `tokens_input` and from `/tmp/tc.jsonl` whether the needle was hit. Use distinct run-ids.

```bash
for LZ in 1 0; do for N in 100 200; do
  export BENCH_TOOLSET_PATH=/tmp/ts.json BENCH_TOOLCALL_LOG=/tmp/tc_$LZ_$N.jsonl BENCH_COLMENA_LAZY=$LZ
  .venv-bench/bin/python -c "import sys;sys.path.insert(0,'runners/_bench_common');from bench_common import scenario_tools as st;import json;open('/tmp/ts.json','w').write(json.dumps(st.generate_toolset($N,'hard',1)))"
  rm -f $BENCH_TOOLCALL_LOG
  PYTHONPATH="$PWD/runners/colmena:$PWD/runners/_bench_common" runners/colmena/.venv/bin/python -m runner --task harness/tasks/07_tools.yaml --variant n$N --run-id d_${LZ}_${N} --model-alias gemini-2.5-flash --proxy-base-url http://127.0.0.1:4000 --output /tmp/d_${LZ}_${N}.json
done; done
```
Expected/derisk: lazy=1 input tokens MUCH lower than lazy=0 at n=200 (catalog vs all schemas), and lazy still hits the needle. If lazy doesn't reduce tokens or doesn't fire `describe_tool`, STOP and report — the experiment premise needs revisiting.

- [ ] **Step 2: Probe whether a competitor's 200 tools 4xx on gemini** — throwaway script: build 200 trivial langchain tools, `bind_tools`, one `invoke` through the proxy. Record whether it returns or raises a 4xx.

```bash
PYTHONPATH="$PWD/runners/langchain:$PWD/runners/_bench_common" runners/langchain/.venv/bin/python - <<'PY'
import os
os.environ["OPENAI_API_KEY"]=os.environ.get("LITELLM_PROXY_API_KEY","sk-x")
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
tools=[]
for i in range(200):
    def f(x: str, _i=i): return "ok"
    tools.append(tool(f"t_{i}")(f))
llm=ChatOpenAI(model="gemini-2.5-flash", base_url="http://127.0.0.1:4000/v1", api_key=os.environ["OPENAI_API_KEY"], temperature=0).bind_tools(tools)
try:
    r=llm.invoke("call t_5 with x=1"); print("OK len", len(str(r)))
except Exception as e:
    print("ERROR", type(e).__name__, str(e)[:200])
PY
```
Expected: discover whether gemini accepts 200 tools (likely OK → hard-error curve may be empty; that's the honest finding) or 4xx.

- [ ] **Step 3: Append findings to spec §9** (token ratio lazy on/off at 200; whether 200 tools 4xx). Commit just the spec edit:
```bash
git add docs/superpowers/specs/2026-06-18-demo07-lazy-tool-loading-design.md
git commit -m "docs(demo07): record derisk findings (lazy token ratio; 200-tool provider behavior)"
```

---

## Phase B — Competitor handlers

> Each builds N tools from `scenario_tools` spec via the framework's native tool API, runs ONE agent turn on `spec.question`, returns `{"answer": <text>}`. Each tool fn calls `scenario_tools.log_tool_call(name, args)` then returns its answer/"not applicable". Mirror the framework's `task04_expert.py` for the tool-calling idiom. Read `BENCH_TOOLSET_PATH` for the spec.

### Task 5: CrewAI handler

**Files:** Create `runners/crewai/runner/tasks/task07_tools.py`; modify `runners/crewai/runner/__main__.py`.

- [ ] **Step 1: Implement** — mirror `runners/crewai/runner/tasks/task04_expert.py` tool idiom. Build N `@tool` functions from the spec (each logs + returns its answer), one `Agent` with all tools, `Crew.kickoff()` on `spec.question`, return `{"answer": str(result)}`.

```python
"""Demo #7 — CrewAI many-tools handler. Registers all N generated tools natively
(no lazy loading — full schemas always sent). Mirrors task04_expert idiom."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
from crewai import Agent, Crew, Task
from crewai.tools import tool
from bench_common import RunnerArgs, scenario_tools

def _make_tool(t: dict):
    def fn(**kwargs) -> str:
        scenario_tools.log_tool_call(t["name"], kwargs)
        return t["answer"]
    fn.__name__ = t["name"]
    return tool(t["name"])(fn)

def run(task_def: dict, llm: Any, args: RunnerArgs):
    spec = json.loads(Path(os.environ["BENCH_TOOLSET_PATH"]).read_text())
    tools = [_make_tool(t) for t in spec["tools"]]
    agent = Agent(role="tool router", goal="call the one correct tool",
                  backstory="Routes to the right tool.", llm=llm, tools=tools,
                  allow_delegation=False, verbose=False)
    crew_task = Task(description=spec["question"], expected_output="the number", agent=agent)
    result = Crew(agents=[agent], tasks=[crew_task], verbose=False).kickoff()
    return {"answer": str(result)}, {"input": 0, "output": 0, "cached": 0}, {}
```
> Note: if CrewAI rejects 200 tools client-side, catch the exception and return `{"answer": "", "error": str(e)}` in extras so the driver records a hard_error.

- [ ] **Step 2: Register** (`task07_tools` import + `HANDLERS["07_tools"]`).
- [ ] **Step 3: Smoke** at n=25 (proxy up): the needle appears in the toolcall log; answer has the number.
- [ ] **Step 4: Commit** — `git commit -m "feat(demo07): crewai many-tools handler"`

### Task 6: LangChain handler
**Files:** Create `runners/langchain/runner/tasks/task07_tools.py`; modify `__main__.py`.
- [ ] **Step 1: Implement** — mirror `runners/langchain/runner/tasks/task04_expert.py` (`llm.bind_tools` + manual invoke→ToolMessage→invoke loop, cap 8). Build N `@tool`s from the spec; the manual loop dispatches whichever tool the model calls (look up by name in a dict) and logs via `scenario_tools.log_tool_call`. Return `{"answer": final_text}`. Wrap in try/except → extras error on client-side failure.
- [ ] **Step 2–4:** register, smoke at n=25, commit `feat(demo07): langchain many-tools handler`.

### Task 7: LangGraph handler
**Files:** Create `runners/langgraph/runner/tasks/task07_tools.py`; modify `__main__.py`.
- [ ] **Step 1: Implement** — mirror `runners/langgraph/runner/tasks/task04_expert.py` (`create_react_agent(llm, tools)`); build N tools from spec; `.invoke({"messages":[HumanMessage(spec["question"])]}, {"recursion_limit": 50})`; extract last AIMessage text. try/except → error.
- [ ] **Step 2–4:** register, smoke, commit `feat(demo07): langgraph many-tools handler`.

### Task 8: LlamaIndex handler
**Files:** Create `runners/llamaindex/runner/tasks/task07_tools.py`; modify `__main__.py`.
- [ ] **Step 1: Implement** — mirror `runners/llamaindex/runner/tasks/task04_expert.py` (`FunctionAgent` + `FunctionTool.from_defaults` per tool, async `.run(max_iterations=...)`). Build N tools; log on call; return final text. try/except → error.
- [ ] **Step 2–4:** register, smoke, commit `feat(demo07): llamaindex many-tools handler`.

### Task 9: Google ADK handler
**Files:** Create `runners/google_adk/runner/tasks/task07_tools.py`; modify `__main__.py`.
- [ ] **Step 1: Implement** — mirror `runners/google_adk/runner/tasks/task04_expert.py` (Agent + plain-callable tools auto-wrapped, `InMemoryRunner`, drain events). Build N callables from spec; each logs + returns; return final text. try/except → error.
- [ ] **Step 2–4:** register, smoke, commit `feat(demo07): google_adk many-tools handler`.

---

## Phase C — Driver, charts, docs

### Task 10: Sweep driver + run wrapper

**Files:**
- Create: `harness/orchestrator/demo_tools_run.py`
- Create: `scripts/run_demo07.sh`
- Test: `harness/orchestrator/tests/test_demo_tools_run.py`

- [ ] **Step 1: Write a focused unit test**

```python
# harness/orchestrator/tests/test_demo_tools_run.py
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demo_tools_run as d

def test_configs_include_colmena_both_modes():
    names = [c["name"] for c in d.CONFIGS]
    assert "colmena-lazy" in names and "colmena-eager" in names
    assert {"crewai", "langchain", "langgraph", "llamaindex", "google_adk"} <= set(names)

def test_grid_dimensions():
    assert d.COUNTS == [5, 10, 25, 50, 100, 200]
    assert d.DIFFICULTIES == ["easy", "medium", "hard"]
    assert d.TRIALS == 5
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement the driver**

```python
# harness/orchestrator/demo_tools_run.py
"""Demo #7 sweep driver. For each (config, count, difficulty, trial): generate the
toolset, write it to a temp file, run the framework handler in its own process with
BENCH_TOOLSET_PATH/BENCH_TOOLCALL_LOG/(colmena)BENCH_COLMENA_LAZY set, then score
from the toolcall log + final answer, and read provider-authoritative input tokens
from the run's proxy spans. Aggregates mean/std per (config, count, difficulty)."""
from __future__ import annotations
import json, os, statistics, subprocess, sys
from pathlib import Path
HARNESS_DIR = Path(__file__).resolve().parents[1]; REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR / "orchestrator")); sys.path.insert(0, str(HARNESS_DIR))
sys.path.insert(0, str(REPO_ROOT / "runners/_bench_common"))
from bench_common import scenario_tools  # noqa: E402
from orchestrator.full_run import venv_python, _proxy_key, _read_spans  # noqa: E402

COUNTS = [5, 10, 25, 50, 100, 200]
DIFFICULTIES = ["easy", "medium", "hard"]
TRIALS = 5
CONFIGS = [
    {"name": "colmena-lazy", "fw": "colmena", "lazy": "1"},
    {"name": "colmena-eager", "fw": "colmena", "lazy": "0"},
    {"name": "crewai", "fw": "crewai"}, {"name": "langchain", "fw": "langchain"},
    {"name": "langgraph", "fw": "langgraph"}, {"name": "llamaindex", "fw": "llamaindex"},
    {"name": "google_adk", "fw": "google_adk"},
]
HEADER_CAPABLE = {"crewai", "langchain", "langgraph", "llamaindex", "google_adk"}


def _tokens_in(spans_dir: Path, run_id: str) -> int:
    f = spans_dir / f"run-{run_id}.jsonl"
    if not f.exists():
        return 0
    return sum(int(json.loads(l).get("tokens_input", 0)) for l in f.read_text().splitlines() if l.strip())


def _run_cell(cfg, count, diff, trial, out_dir, proxy, spans_dir):
    spec = scenario_tools.generate_toolset(count, diff, seed=trial)
    run_id = f"t7-{cfg['name']}-{count}-{diff}-{trial}"
    ts_path = out_dir / f"{run_id}.toolset.json"; ts_path.write_text(json.dumps(spec))
    tc_path = out_dir / f"{run_id}.toolcalls.jsonl"; tc_path.unlink(missing_ok=True)
    out_path = out_dir / f"{run_id}.json"
    env = os.environ.copy()
    env.update({"BENCH_RUN_ID": run_id, "LITELLM_PROXY_API_KEY": _proxy_key(),
                "BENCH_TOOLSET_PATH": str(ts_path), "BENCH_TOOLCALL_LOG": str(tc_path),
                "PYTHONPATH": f"{REPO_ROOT/'runners'/cfg['fw']}:{REPO_ROOT/'runners'/'_bench_common'}"})
    if "lazy" in cfg:
        env["BENCH_COLMENA_LAZY"] = cfg["lazy"]
    cmd = [str(venv_python(cfg["fw"])), "-m", "runner", "--task",
           str(REPO_ROOT / "harness/tasks/07_tools.yaml"), "--variant", f"n{count}",
           "--run-id", run_id, "--model-alias", "gemini-2.5-flash",
           "--proxy-base-url", proxy, "--output", str(out_path)]
    hard_error = False
    try:
        p = subprocess.run(cmd, env=env, cwd=REPO_ROOT, timeout=180, capture_output=True)
        hard_error = p.returncode != 0
    except Exception:
        hard_error = True
    answer = ""
    if out_path.exists():
        ro = json.loads(out_path.read_text())
        answer = ((ro.get("answer") or {}) if isinstance(ro.get("answer"), dict) else {}).get("answer", "") \
            or (ro.get("answer") if isinstance(ro.get("answer"), str) else "")
        if (ro.get("extras") or {}).get("error"):
            hard_error = True
    sc = scenario_tools.score(spec, scenario_tools.read_tool_calls(tc_path), answer)
    return {"tokens_in": _tokens_in(spans_dir, run_id), "hard_error": hard_error, **sc}


def main():
    out_dir = REPO_ROOT / "runs/demo07/raw"; out_dir.mkdir(parents=True, exist_ok=True)
    spans_dir = REPO_ROOT / "proxy/spans"; proxy = "http://127.0.0.1:4000"
    rows = []
    for cfg in CONFIGS:
        for count in COUNTS:
            for diff in DIFFICULTIES:
                cells = [_run_cell(cfg, count, diff, t, out_dir, proxy, spans_dir) for t in range(TRIALS)]
                def m(k): return round(statistics.mean(c[k] for c in cells), 4)
                rows.append({"config": cfg["name"], "n_tools": count, "difficulty": diff,
                             "selection_acc": m("selection_ok"), "arg_acc": m("arg_ok"),
                             "answer_acc": m("answer_ok"),
                             "tokens_in_mean": round(statistics.mean(c["tokens_in"] for c in cells), 1),
                             "hard_error_rate": m("hard_error")})
                print(f"{cfg['name']:14s} n={count:3d} {diff:6s} ans={rows[-1]['answer_acc']:.2f} "
                      f"tok={rows[-1]['tokens_in_mean']:.0f} err={rows[-1]['hard_error_rate']:.2f}")
    od = REPO_ROOT / "runs/demo07"; od.mkdir(parents=True, exist_ok=True)
    (od / "summary.json").write_text(json.dumps(rows, indent=2))
    import csv
    with (od / "summary.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run unit test → PASS.**

- [ ] **Step 5: Write `scripts/run_demo07.sh`** (mirror `scripts/run_demo06.sh`): source .env, start proxy on `.venv-bench` PATH (no mask audit needed), wait for readiness, run `.venv-bench/bin/python harness/orchestrator/demo_tools_run.py`, kill proxy on exit.

- [ ] **Step 6: Smoke the driver on a TINY grid** — temporarily set `COUNTS=[5,10]`, `DIFFICULTIES=["easy"]`, `TRIALS=1` via env override or a quick edit, run `bash scripts/run_demo07.sh`, confirm `runs/demo07/summary.json` has rows for all 7 configs. Restore the full grid.

- [ ] **Step 7: Commit** — `git add harness/orchestrator/demo_tools_run.py harness/orchestrator/tests/test_demo_tools_run.py scripts/run_demo07.sh && git commit -m "feat(demo07): sweep driver + run wrapper"`

---

### Task 11: Charts

**Files:** Create `harness/orchestrator/demo07_plots.py`

- [ ] **Step 1: Implement** (mirror `demo06_plots.py`; reads `runs/demo07/summary.json`). For each difficulty facet produce: `accuracy_vs_tools_<diff>.png` (answer_acc, 7 lines), `tokens_vs_tools_<diff>.png` (log y, 7 lines), and one `error_rate_vs_tools.png`. Plus `bars_at_200.png` (tokens + answer_acc per config at n=200, hard difficulty). colmena-lazy highlighted green; colmena-eager as the dashed internal control.

```python
# harness/orchestrator/demo07_plots.py
from __future__ import annotations
import json, sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
HARNESS_DIR = Path(__file__).resolve().parents[1]
ROWS = json.loads((HARNESS_DIR.parent / "runs/demo07/summary.json").read_text())
OUT = HARNESS_DIR.parent / "runs/demo07/plots"; OUT.mkdir(parents=True, exist_ok=True)
CONFIGS = ["colmena-lazy", "colmena-eager", "crewai", "langchain", "langgraph", "llamaindex", "google_adk"]
COLORS = {"colmena-lazy": "#1f9d55", "colmena-eager": "#7fbf7f", "crewai": "#e15759",
          "langchain": "#4e79a7", "langgraph": "#f28e2b", "llamaindex": "#b07aa1", "google_adk": "#17a2b8"}

def _line(metric, diff, ylabel, logy, path, title):
    fig, ax = plt.subplots(figsize=(8, 5))
    for c in CONFIGS:
        pts = sorted([(r["n_tools"], r[metric]) for r in ROWS if r["config"] == c and r["difficulty"] == diff])
        if pts:
            xs, ys = zip(*pts)
            ax.plot(xs, ys, "--o" if c == "colmena-eager" else "-o", color=COLORS[c], label=c,
                    linewidth=2.4 if c.startswith("colmena") else 1.6)
    if logy: ax.set_yscale("log")
    ax.set_xlabel("number of tools"); ax.set_ylabel(ylabel); ax.set_title(title)
    ax.legend(fontsize=7); ax.grid(alpha=0.3, which="both")
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)

def main():
    for diff in ["easy", "medium", "hard"]:
        _line("answer_acc", diff, "answer accuracy", False, OUT / f"accuracy_vs_tools_{diff}.png",
              f"Demo #7 — accuracy vs #tools (needle: {diff})")
        _line("tokens_in_mean", diff, "input tokens (log)", True, OUT / f"tokens_vs_tools_{diff}.png",
              f"Demo #7 — input tokens vs #tools (needle: {diff})")
    _line("hard_error_rate", "hard", "hard-error rate", False, OUT / "error_rate_vs_tools.png",
          "Demo #7 — hard-error rate vs #tools (needle: hard)")
    print("charts →", OUT)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run** after the sweep → PNGs in `runs/demo07/plots/`. **Step 3: Commit** `feat(demo07): charts`.

---

### Task 12: Docs

**Files:** Create `docs/demos/demo07-many-tools.md`, `docs/demos/demo07-replication.md`

- [ ] **Step 1: Pitch doc** — mirror `docs/demos/task04-csv.md`. Lead with the headline from `summary.json` (lazy flat tokens + sustained accuracy vs the decline of eager/competitors as tools grow, worsening with difficulty). Embed the charts. Be honest about: lazy pays for `describe_tool` round-trips (counted); whether the hard-error appeared on gemini (from the derisk); colmena-eager as the internal control proving the feature is the cause.
- [ ] **Step 2: Replication doc** — `bash scripts/run_demo07.sh` → `runs/demo07/`; then `demo07_plots.py`. Document the env (`BENCH_TOOLSET_PATH`, `BENCH_TOOLCALL_LOG`, `BENCH_COLMENA_LAZY`) and the ~630-run cost.
- [ ] **Step 3: Commit** `docs(demo07): pitch + replication`.

---

## Self-review notes (for the executor)

- **Spec coverage:** generator+difficulty tiers+distinguishable summaries (T1), task YAML (T2), colmena lazy on/off (T3), derisk lazy-token-ratio + 200-tool probe (T4), 5 competitors (T5–T9), sweep driver with the 7×6×3×5 grid + scoring + provider tokens (T10), charts faceted by difficulty (T11), docs (T12). Fairness (same spec file to all) is enforced by the driver writing one toolset per cell and pointing every config at it.
- **Verification gates (not placeholders):**
  1. Colmena tool-config schema for many python_script tools + `lazy_tool_loading` must validate/run — resolved by the Task 3 smoke (adjust schema/port names until the needle is hit and `describe_tool` fires).
  2. The colmena `_tool_code` arg-capture (reading injected globals) may need tweaking to match how python_script exposes tool args — confirm in the Task 3 smoke that `/tmp/tc.jsonl` shows real args.
  3. The emitted output schema (`answer`/`extras`) — confirm against `bench_common.core` emit during the Task 3/Task 5 smokes and adjust the driver's answer extraction.
  4. Whether gemini 4xx's at 200 tools — resolved in Task 4; if not, the hard-error curve is honestly ~0 and accuracy+tokens carry the result.
- **Cost:** full grid ≈ 630 runs; run via `run_demo07.sh` as a background batch. Consider running difficulties/counts incrementally if needed.
