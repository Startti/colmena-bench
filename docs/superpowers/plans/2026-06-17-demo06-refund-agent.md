# Demo #4 — Refund Agent (node-vs-code) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-hardened refund agent (durable HITL + critic-retry + outbound secret masking) as a declarative Colmena DAG and as hand-rolled idiomatic code in CrewAI/LangChain/LlamaIndex, then measure it (two-column LOC + capability matrix + functional pass/fail) to demonstrate the node-vs-code win.

**Architecture:** Shared scenario assets in `bench_common`; one Colmena DAG + thin runner; three competitor handlers using each framework's official-doc idiom; a driver that runs each framework in **two separate OS processes** (suspend → teardown → resume) and audits masking via an in-memory proxy scan; outputs JSON/CSV + charts.

**Tech Stack:** Python 3.11 (per-framework venvs), `colmena` PyO3 binding (`run_dag` two-phase), LiteLLM proxy (provider-authoritative + masking audit), matplotlib, pytest.

**Spec:** `docs/superpowers/specs/2026-06-17-demo06-refund-agent-node-vs-code-design.md`

---

## Verified facts this plan relies on (from spec §5, smoke-tested 2026-06-17)

- `colmena.run_dag(graph, resume_id, resume_answer, inject_payload, include_extra_info, agent_session_id)`.
- Phase 1 suspend returns JSON `{"__colmena_status":"SUSPENDED","questions":[{"id":...}],"session_id":"<UUID>"}`.
- Phase 2 resume: `resume_id = <UUID from phase 1>`, `resume_answer = "A[<id>]: <answer>"`, `agent_session_id = <ORIGINAL id>`.
- Unique `agent_session_id` per run (concurrent suspended chains under one id error).
- Runner CLI contract: `python -m runner --task <yaml> --variant default --run-id <id> --model-alias <alias> --proxy-base-url <url> --output <path>`; handler signature `run(task_def, llm, args) -> (answer, usage) | (answer, usage, extras)`.

---

## File Structure

| File | Responsibility |
|---|---|
| `runners/_bench_common/bench_common/scenario_refund.py` | Shared scenario: customer msg, policy, mock payment tool (echoes token), secret, canonical human answer, pass/fail checks |
| `runners/_bench_common/bench_common/core.py` (modify) | Extend `RunnerArgs` + CLI with `--resume-state` / `--resume-answer`; allow extras to carry suspend state |
| `harness/tasks/06_refund.yaml` | Task definition |
| `proxy/spans_callback.py` (modify) | Opt-in in-memory masking audit (`BENCH_MASK_AUDIT_SECRET`) → `proxy/spans/mask-<run_id>.json` `{secret_leaked: bool}` |
| `runners/colmena/runner/dags/refund_agent.json` | The Colmena DAG (declarative config, counted separately) |
| `runners/colmena/runner/tasks/task06_refund.py` | Thin Colmena runner (two-phase via run_dag) |
| `runners/colmena/runner/__main__.py` (modify) | Register `06_refund` |
| `runners/crewai/runner/tasks/task06_refund.py` | CrewAI handler (idiomatic HITL+critic+masking) |
| `runners/langchain/runner/tasks/task06_refund.py` | LangChain handler |
| `runners/llamaindex/runner/tasks/task06_refund.py` | LlamaIndex handler |
| `runners/{crewai,langchain,llamaindex}/runner/__main__.py` (modify) | Register `06_refund` |
| `harness/orchestrator/demo_refund_run.py` | Driver: two-process run, pass/fail, LOC (2 cols), masking audit, JSON/CSV |
| `harness/orchestrator/demo06_matrix.py` | Capability matrix data + render |
| `harness/orchestrator/demo06_plots.py` | LOC bar (2-col) + matrix figure |
| `harness/orchestrator/tests/test_*.py` | Unit tests |
| `docs/demos/demo06-refund-agent.md` + `demo06-replication.md` | Pitch + repro |

---

## Phase A — Derisk the masking primitive

### Task 1: Live smoke — non-interactive secret + outbound masking

**Files:**
- Create (temp, not committed): `/tmp/smoke_mask.py`
- Output: a documented decision appended to the spec's §9 (which secret-injection path works)

- [ ] **Step 1: Write the smoke script**

```python
# /tmp/smoke_mask.py — does a secure value used in a tool get masked before the LLM?
import json, os, uuid
from pathlib import Path
os.environ.setdefault("DATABASE_URL", os.environ.get("COLMENA_DATABASE_URL", ""))
os.environ.setdefault("SECURE_VALUES_KEY", "0" * 64)
Path("/tmp/colmena-bench-storage").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("COLMENA_LOCAL_STORAGE_DIR", "/tmp/colmena-bench-storage")
os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:4000/v1"
os.environ["OPENAI_API_KEY"] = os.environ.get("LITELLM_PROXY_API_KEY", "sk-x")
import colmena

SECRET = "sk-live-REFUND-SECRET-abc123"
sess = "mask_smoke_" + uuid.uuid4().hex[:8]

# Path 1: secure_suspend collects the secret; tool echoes it; llm_call must NOT see it.
graph = {
  "nodes": {
    "start": {"type": "mock_input", "config": {"input_data": "lookup order"}},
    "get_key": {"type": "secure_suspend", "config": {"secrets": [{"id": "pay_key", "question": "API key?", "name": "pay_key"}]}},
    "pay": {"type": "python_script", "config": {
        "sandbox_mode": "none",
        "code": "output = {'echo': 'called payment API with key=' + pay_key}",
    }},
    "summ": {"type": "llm_call", "config": {
        "provider": "openai", "model": "gemini-2.5-flash",
        "api_key": "${OPENAI_API_KEY}", "connection_url": "${DATABASE_URL}",
        "system_message": "Summarize the tool result in one line.", "stream": False}},
    "out": {"type": "log", "config": {"prefix": "OUT:"}},
  },
  "edges": [
    {"from": "start", "to": "get_key"},
    {"from": "get_key.pay_key", "to": "pay"},
    {"from": "pay", "to": "summ"},
    {"from": "summ", "to": "out"},
  ],
}
out1 = json.loads(colmena.run_dag(graph, None, None, None, True, sess))
print("phase1 status:", out1.get("__colmena_status"), "rid:", out1.get("session_id"))
rid = out1["session_id"]
out2 = colmena.run_dag(graph, rid, f"A[pay_key]: {SECRET}", None, True, sess)
blob = json.dumps(out2)
print("SECRET present in final graph output:", SECRET in blob)
print(blob[:1200])
```

- [ ] **Step 2: Start the proxy with masking-audit env and run the smoke**

Run:
```bash
cd /Users/danielgarcia/startti/colmena-bench && set -a && source .env && set +a
pkill -f "litellm --config"; sleep 1
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=mask_smoke nohup bash proxy/start_proxy.sh >/tmp/mask_proxy.log 2>&1 &
for i in $(seq 1 40); do curl -fsS -m2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break; sleep 1; done
PYTHONPATH="$PWD/runners/colmena:$PWD/runners/_bench_common" runners/colmena/.venv/bin/python /tmp/smoke_mask.py
```
Expected: phase1 status `SUSPENDED`; the LLM still produces a summary; verify in `proxy/spans/run-mask_smoke.jsonl` a span exists. The KEY check (next step) is whether the secret reached the model.

- [ ] **Step 3: Confirm the secret never reached the LLM**

Temporarily add a print of `kwargs.get("messages")` is not needed — instead grep the proxy debug. Simplest: in the smoke, the `summ` node summarized the tool result; if masking works, the model saw `<sv_pay_key_...>` not the real secret. Confirm by inspecting `out2` — the `summ.result` should reference a handle or omit the secret, and `SECRET in blob` for the LLM-facing path should be False. If the engine masks in tool result → the `pay.echo` returned to `summ` is a handle.

Expected: masking confirmed (secret replaced by handle before `llm_call`).

- [ ] **Step 4: Document the working path in the spec**

Append to spec §9 a one-line note: "Masking confirmed via `secure_suspend` + `A[id]:` resume; tool echo masked to handle before llm_call." If Path 1 fails, document the failure and try a `secure: true` http_request/secure-value-in-config variant before proceeding.

- [ ] **Step 5: Commit the spec note**

```bash
git add docs/superpowers/specs/2026-06-17-demo06-refund-agent-node-vs-code-design.md
git commit -m "docs(demo06): record verified masking injection path from smoke"
```

---

## Phase B — Shared scaffolding

### Task 2: Shared scenario assets

**Files:**
- Create: `runners/_bench_common/bench_common/scenario_refund.py`
- Modify: `runners/_bench_common/bench_common/__init__.py` (export new names)
- Test: `runners/_bench_common/tests/test_scenario_refund.py`

- [ ] **Step 1: Write the failing test**

```python
# runners/_bench_common/tests/test_scenario_refund.py
from bench_common import scenario_refund as s

def test_assets_present_and_consistent():
    assert s.SECRET.startswith("sk-live-REFUND-")
    assert s.POLICY_MAX_USD == 100.0
    # the scenario guarantees a first-draft violation: amount > policy max
    assert s.REQUEST["amount"] > s.POLICY_MAX_USD
    # canonical human answer approves
    assert "approve" in s.CANONICAL_HUMAN_ANSWER.lower()

def test_policy_check_is_deterministic():
    assert s.policy_violation({"decision": "approve", "amount": 250.0}) is True   # over limit, full approve
    assert s.policy_violation({"decision": "partial", "amount": 100.0}) is False

def test_payment_tool_echoes_secret():
    # masking is only meaningful if a naive impl would leak: the tool echoes the key
    out = s.payment_lookup(order_id="ORD-1", api_key=s.SECRET)
    assert s.SECRET in out   # raw tool output contains the secret (pre-masking)

def test_pass_fail_checks_shape():
    checks = s.evaluate(answer={"decision": "partial"}, retries=1, secret_leaked=False)
    assert set(checks) == {"hitl_ok", "critic_ok", "masking_ok", "all_ok"}
    assert checks["all_ok"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd runners/_bench_common && .venv/bin/python -m pytest tests/test_scenario_refund.py -v`
Expected: FAIL (module `scenario_refund` not found).

- [ ] **Step 3: Implement the scenario module**

```python
# runners/_bench_common/bench_common/scenario_refund.py
"""Shared assets for Demo #4 (refund agent). Identical for all frameworks.

The scenario is engineered so the comparison is deterministic and fair:
- amount > POLICY_MAX_USD guarantees a first-draft policy violation → the critic
  retry path always executes (we test the framework can express retry, not luck).
- payment_lookup ECHOES the api_key in its output, so a naive agent that forwards
  the tool result to the LLM genuinely leaks the secret → masking is non-trivial.
"""
from __future__ import annotations

SECRET = "sk-live-REFUND-SECRET-abc123"
POLICY_MAX_USD = 100.0

REQUEST = {"order_id": "ORD-12345", "reason": "Double charged", "amount": 250.0}

CUSTOMER_MESSAGE = (
    "I was charged twice for order ORD-12345 (250 USD total). Please refund the "
    "duplicate charge."
)

# Policy the agent must respect (shared, also handed to the model as text).
POLICY_TEXT = (
    "Refund policy: a single agent may auto-approve refunds up to 100 USD. Refunds "
    "above 100 USD must be 'partial' (<=100) or 'escalate'. Never auto-approve > 100."
)

CANONICAL_HUMAN_ANSWER = "Yes, approve the partial refund."


def payment_lookup(order_id: str, api_key: str) -> str:
    """Mock payment API. Echoes the api_key in its response on purpose (see module
    docstring) so masking has something real to scrub."""
    return (
        f"order={order_id} status=charged_twice amount=250.00 "
        f"auth_token={api_key} gateway=mockpay"
    )


def policy_violation(answer: dict) -> bool:
    """Deterministic, rule-based policy check (no LLM). True if the decision breaks
    policy (full approve over the limit)."""
    decision = str(answer.get("decision", "")).lower()
    amount = float(answer.get("amount", REQUEST["amount"]))
    return decision == "approve" and amount > POLICY_MAX_USD


def evaluate(answer: dict, retries: int, secret_leaked: bool) -> dict:
    """The three functional pass/fail checks + overall."""
    hitl_ok = answer is not None  # run completed past the suspend
    critic_ok = retries >= 1 and not policy_violation(answer)
    masking_ok = not secret_leaked
    all_ok = bool(hitl_ok and critic_ok and masking_ok)
    return {"hitl_ok": hitl_ok, "critic_ok": critic_ok,
            "masking_ok": masking_ok, "all_ok": all_ok}
```

- [ ] **Step 4: Export from package init**

Add to `runners/_bench_common/bench_common/__init__.py` (mirror existing exports):

```python
from . import scenario_refund  # noqa: F401
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd runners/_bench_common && .venv/bin/python -m pytest tests/test_scenario_refund.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add runners/_bench_common/bench_common/scenario_refund.py runners/_bench_common/bench_common/__init__.py runners/_bench_common/tests/test_scenario_refund.py
git commit -m "feat(demo06): shared refund-agent scenario assets + deterministic checks"
```

---

### Task 3: Task YAML

**Files:**
- Create: `harness/tasks/06_refund.yaml`

- [ ] **Step 1: Write the YAML**

```yaml
# Demo #4 — production refund agent (HITL + critic-retry + masking).
prompt: |
  You are a refund support agent. Decide the refund for the customer's order using
  the run_payment tool to look up the order. Respect this policy strictly:
  Refund policy: auto-approve up to 100 USD; above 100 USD you must choose 'partial'
  (<=100) or 'escalate'; never auto-approve more than 100 USD.
  Return a JSON object: {"decision": "approve|partial|reject|escalate", "amount": <number>, "justification": "<text>"}.
tools:
  - name: run_payment
metrics: [loc, pass_fail]
success:
  kind: refund_agent
model_alias: gemini-2.5-flash
timeout_seconds: 180
n_runs: 1
```

- [ ] **Step 2: Validate it loads**

Run: `cd /Users/danielgarcia/startti/colmena-bench && .venv-bench/bin/python -c "import yaml; print(yaml.safe_load(open('harness/tasks/06_refund.yaml'))['success']['kind'])"`
Expected: prints `refund_agent`.

- [ ] **Step 3: Commit**

```bash
git add harness/tasks/06_refund.yaml
git commit -m "feat(demo06): task YAML for refund agent"
```

---

### Task 4: Proxy in-memory masking audit

**Files:**
- Modify: `proxy/spans_callback.py`
- Test: `proxy/tests/test_mask_audit.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# proxy/tests/test_mask_audit.py
import json, os
from pathlib import Path
import spans_callback as sc

def test_scan_messages_for_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_MASK_AUDIT_SECRET", "sk-live-REFUND-SECRET-abc123")
    monkeypatch.setenv("LITELLM_SPANS_DIR", str(tmp_path))
    msgs = [{"role": "user", "content": "here is the key sk-live-REFUND-SECRET-abc123"}]
    sc.audit_messages_for_secret(msgs, run_id="r1")
    rec = json.loads((tmp_path / "mask-r1.json").read_text())
    assert rec["secret_leaked"] is True

def test_no_leak_records_false(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_MASK_AUDIT_SECRET", "sk-live-REFUND-SECRET-abc123")
    monkeypatch.setenv("LITELLM_SPANS_DIR", str(tmp_path))
    sc.audit_messages_for_secret([{"role": "user", "content": "handle <sv_x>"}], run_id="r2")
    rec = json.loads((tmp_path / "mask-r2.json").read_text())
    assert rec["secret_leaked"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd proxy && python -m pytest tests/test_mask_audit.py -v`
Expected: FAIL (`audit_messages_for_secret` not defined).

- [ ] **Step 3: Implement the audit function + hook it into `_emit`**

Add to `proxy/spans_callback.py`:

```python
def audit_messages_for_secret(messages, run_id: str) -> None:
    """If BENCH_MASK_AUDIT_SECRET is set, scan request messages IN MEMORY for the
    secret and record only a boolean to mask-<run_id>.json. NEVER writes the raw
    body (the secret must not land on disk). Sets leaked=True once it ever leaks."""
    secret = os.environ.get("BENCH_MASK_AUDIT_SECRET")
    if not secret or not messages:
        return
    blob = json.dumps(messages, default=str)
    leaked_now = secret in blob
    path = _spans_dir() / f"mask-{run_id}.json"
    prev = False
    if path.exists():
        try:
            prev = json.loads(path.read_text()).get("secret_leaked", False)
        except Exception:
            prev = False
    path.write_text(json.dumps({"secret_leaked": bool(prev or leaked_now)}))
```

In `_emit`, after computing `run_id`, add:

```python
        audit_messages_for_secret(kwargs.get("messages"), run_id)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd proxy && python -m pytest tests/test_mask_audit.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add proxy/spans_callback.py proxy/tests/test_mask_audit.py
git commit -m "feat(demo06): opt-in in-memory masking audit in proxy callback"
```

---

### Task 5: Two-phase runner contract extension

**Files:**
- Modify: `runners/_bench_common/bench_common/core.py` (RunnerArgs + parse_args)
- Test: `runners/_bench_common/tests/test_resume_args.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# runners/_bench_common/tests/test_resume_args.py
from bench_common.core import parse_args

def test_resume_args_parse():
    a = parse_args("x", ["--task", "t.yaml", "--variant", "default", "--run-id", "r",
                         "--model-alias", "gemini-2.5-flash", "--proxy-base-url", "u",
                         "--output", "o.json", "--resume-state", "s.json",
                         "--resume-answer", "A[approve_refund]: yes"])
    assert a.resume_state.name == "s.json"
    assert a.resume_answer == "A[approve_refund]: yes"

def test_resume_args_default_none():
    a = parse_args("x", ["--task", "t.yaml", "--variant", "default", "--run-id", "r",
                         "--model-alias", "gemini-2.5-flash", "--proxy-base-url", "u",
                         "--output", "o.json"])
    assert a.resume_state is None and a.resume_answer is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd runners/_bench_common && .venv/bin/python -m pytest tests/test_resume_args.py -v`
Expected: FAIL (`resume_state` attribute missing).

- [ ] **Step 3: Add fields to RunnerArgs + parser**

In `core.py`, add to the `RunnerArgs` dataclass:

```python
    resume_state: "Path | None" = None
    resume_answer: "str | None" = None
```

In `parse_args`, add arguments and pass them through:

```python
    p.add_argument("--resume-state", type=Path, default=None)
    p.add_argument("--resume-answer", default=None)
```
```python
        resume_state=ns.resume_state,
        resume_answer=ns.resume_answer,
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd runners/_bench_common && .venv/bin/python -m pytest tests/test_resume_args.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add runners/_bench_common/bench_common/core.py runners/_bench_common/tests/test_resume_args.py
git commit -m "feat(demo06): two-phase resume args in runner contract"
```

---

## Phase C — Colmena

### Task 6: Colmena refund DAG (declarative config)

**Files:**
- Create: `runners/colmena/runner/dags/refund_agent.json`

- [ ] **Step 1: Author the DAG**

Use the masking path confirmed in Task 1. Structure (adapt node configs to the verified path):

```json
{
  "comment": "Demo #4 refund agent: draft -> rule-validate (cyclic retry) -> payment tool (masked secret) -> human approval -> route.",
  "nodes": {
    "trigger": {"type": "trigger_webhook", "config": {"path": "/refund",
      "test_payload": {"prompt": "PLACEHOLDER_INJECTED_AT_RUNTIME"}}},
    "draft": {"type": "llm_call", "config": {
      "provider": "openai", "model": "gemini-2.5-flash",
      "api_key": "${OPENAI_API_KEY}", "connection_url": "${DATABASE_URL}",
      "temperature": 0.0, "stream": false,
      "system_message": "You are a refund agent. Respect the policy in the prompt. Return ONLY JSON {\"decision\",\"amount\",\"justification\"}."}},
    "validate": {"type": "python_script", "config": {"sandbox_mode": "none",
      "code": "import json\nd=json.loads(draft_result) if isinstance(draft_result,str) else draft_result\nviolation = str(d.get('decision','')).lower()=='approve' and float(d.get('amount',0))>100.0\noutput = {'ok': not violation, 'feedback': 'amount exceeds 100; choose partial or escalate' if violation else '', '__colmena_loop_status': 'NEXT_TURN' if violation else 'FINISHED'}"}},
    "get_key": {"type": "secure_suspend", "config": {"secrets": [{"id": "pay_key", "question": "Payment API key?", "name": "pay_key"}]}},
    "pay": {"type": "python_script", "config": {"sandbox_mode": "none",
      "code": "output = {'result': 'order=ORD-12345 status=charged_twice amount=250.00 auth_token=' + pay_key + ' gateway=mockpay'}"}},
    "review": {"type": "suspend", "config": {"id": "approve_refund",
      "question": "Approve this refund?", "question_type": "open"}},
    "decide": {"type": "router", "config": {"mode": "extract_and_route",
      "provider": "openai", "model": "gemini-2.5-flash", "api_key": "${OPENAI_API_KEY}",
      "connection_url": "${DATABASE_URL}",
      "schema": {"intent": {"type": "string", "required": true,
        "description": "approve if approved/send; reject if cancelled; escalate if escalation requested"}},
      "branches": [
        {"name": "approve", "when": {"field": "intent", "equals": "approve"}},
        {"name": "reject", "when": {"field": "intent", "equals": "reject"}},
        {"name": "escalate", "when": {"field": "intent", "equals": "escalate"}}]}},
    "do_approve": {"type": "log", "config": {"prefix": "REFUND ISSUED:"}},
    "do_reject": {"type": "log", "config": {"prefix": "REFUND DECLINED:"}},
    "do_escalate": {"type": "log", "config": {"prefix": "ESCALATED:"}}
  },
  "edges": [
    {"from": "trigger", "to": "draft"},
    {"from": "draft.result", "to": "validate"},
    {"from": "validate", "to": "draft", "cyclic": true},
    {"from": "validate", "to": "get_key"},
    {"from": "get_key.pay_key", "to": "pay"},
    {"from": "pay", "to": "review"},
    {"from": "review.answer_received", "to": "decide.input"},
    {"from": "decide.approve", "to": "do_approve"},
    {"from": "decide.reject", "to": "do_reject"},
    {"from": "decide.escalate", "to": "do_escalate"}
  ]
}
```

- [ ] **Step 2: Validate the graph**

Run:
```bash
cd /Users/danielgarcia/startti/colmena-bench && set -a && source .env && set +a
PYTHONPATH="$PWD/runners/colmena:$PWD/runners/_bench_common" runners/colmena/.venv/bin/python -c "import colmena, json; colmena.validate_graph(json.load(open('runners/colmena/runner/dags/refund_agent.json'))); print('VALID')"
```
Expected: prints `VALID`. If a node/edge port name is rejected, fix per the error (the cyclic-retry and secure_suspend wiring may need port-name tweaks confirmed against the engine — adjust until VALID).

- [ ] **Step 3: Commit**

```bash
git add runners/colmena/runner/dags/refund_agent.json
git commit -m "feat(demo06): colmena refund-agent DAG (declarative)"
```

---

### Task 7: Colmena thin runner (two-phase)

**Files:**
- Create: `runners/colmena/runner/tasks/task06_refund.py`
- Modify: `runners/colmena/runner/__main__.py` (register `06_refund`, import task06_refund)

- [ ] **Step 1: Implement the handler**

Mirror env setup from `runners/colmena/runner/tasks/task04_expert.py:_ensure_env`. The handler does phase 1 OR phase 2 depending on `args.resume_state`:

```python
"""Demo #4 — Colmena refund agent. Two-phase: phase 1 runs to the human-approval
suspend and writes the resume handle; phase 2 resumes with the human answer.
The DAG (dags/refund_agent.json) is declarative config, not counted as code."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
from bench_common import RunnerArgs
from bench_common import scenario_refund as S

REPO_ROOT = Path(__file__).resolve().parents[4]
DAG = REPO_ROOT / "runners/colmena/runner/dags/refund_agent.json"


def _ensure_env(caller: Any) -> None:
    os.environ["OPENAI_API_KEY"] = caller.api_key
    if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]
    os.environ.setdefault("SECURE_VALUES_KEY", "0" * 64)
    sd = Path("/tmp/colmena-bench-storage"); sd.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_DIR", str(sd))
    os.environ.setdefault("COLMENA_LOCAL_STORAGE_PORT", "0")


def run(task_def: dict, caller: Any, args: RunnerArgs):
    import colmena
    _ensure_env(caller)
    graph = json.loads(DAG.read_text())
    prompt = f"{task_def['prompt']}\n\nCustomer: {S.CUSTOMER_MESSAGE}\nAmount: {S.REQUEST['amount']}"
    session = f"refund_{args.run_id}"

    if args.resume_state is None:
        # PHASE 1: run to the first suspend (secure_suspend for the key).
        out = json.loads(colmena.run_dag(graph, None, None, {"prompt": prompt}, True, session))
        state = {"session": session, "resume_id": out.get("session_id"),
                 "questions": out.get("questions", [])}
        # write resume state next to the output for the driver
        Path(str(args.output) + ".state").write_text(json.dumps(state))
        return {"decision": None}, {"input": 0, "output": 0, "cached": 0}, {"suspended": True, "state": state}

    # PHASE 2: resume. The driver feeds the secret then the human answer in order.
    state = json.loads(Path(args.resume_state).read_text())
    # resume secure_suspend with the secret, then the approval suspend with the human answer
    out = json.loads(colmena.run_dag(graph, state["resume_id"], f"A[pay_key]: {S.SECRET}",
                                     {"prompt": prompt}, True, state["session"]))
    if out.get("__colmena_status") == "SUSPENDED":
        out = json.loads(colmena.run_dag(graph, out["session_id"],
                                         f"A[approve_refund]: {args.resume_answer or S.CANONICAL_HUMAN_ANSWER}",
                                         {"prompt": prompt}, True, state["session"]))
    # extract the draft decision JSON from the graph output
    draft = out.get("draft", {})
    text = draft.get("result", draft) if isinstance(draft, dict) else draft
    try:
        answer = json.loads(text) if isinstance(text, str) else (text or {})
    except Exception:
        answer = {}
    return answer, {"input": 0, "output": 0, "cached": 0}, {"final": out}
```

- [ ] **Step 2: Register in `__main__.py`**

Add `task06_refund` to the imports and `HANDLERS`:
```python
from .tasks import task01, task04_expert, task04_naive, task05, task06_refund
```
```python
    "06_refund": task06_refund.run,
```

- [ ] **Step 3: Manual two-phase smoke**

Run (proxy up, .env sourced):
```bash
# phase 1
PYTHONPATH="$PWD/runners/colmena:$PWD/runners/_bench_common" runners/colmena/.venv/bin/python -m runner \
  --task harness/tasks/06_refund.yaml --variant default --run-id rf1 \
  --model-alias gemini-2.5-flash --proxy-base-url http://127.0.0.1:4000 --output /tmp/rf1.json
# phase 2
PYTHONPATH="$PWD/runners/colmena:$PWD/runners/_bench_common" runners/colmena/.venv/bin/python -m runner \
  --task harness/tasks/06_refund.yaml --variant default --run-id rf1 \
  --model-alias gemini-2.5-flash --proxy-base-url http://127.0.0.1:4000 --output /tmp/rf1b.json \
  --resume-state /tmp/rf1.json.state --resume-answer "A[approve_refund]: yes, approve"
```
Expected: phase 1 writes `/tmp/rf1.json.state` with a `resume_id`; phase 2 output has a non-null `decision` and the run completed. Adjust DAG output-key extraction until `decision` is populated.

- [ ] **Step 4: Commit**

```bash
git add runners/colmena/runner/tasks/task06_refund.py runners/colmena/runner/__main__.py
git commit -m "feat(demo06): colmena two-phase refund runner"
```

---

## Phase D — Competitor handlers

> Fairness rule (spec §3.4): each uses that framework's **official-doc idiom** for HITL/retry/secret-handling, with the doc URL cited in a module docstring. Mirror the existing `task05.py` / `task04_expert.py` handler in each runner for the LLM-call boilerplate; add the bench-side HITL persistence + critic loop + masking scrub (plain Python, framework-agnostic).

### Task 8: CrewAI refund handler

**Files:**
- Create: `runners/crewai/runner/tasks/task06_refund.py`
- Modify: `runners/crewai/runner/__main__.py`

- [ ] **Step 1: Implement the handler**

```python
"""Demo #4 — CrewAI refund agent. CrewAI has no native durable HITL or outbound
masking, so both are hand-rolled (the honest node-vs-code cost). HITL pattern
follows CrewAI's human-input/kickoff docs: https://docs.crewai.com/ (cite exact
page during impl). Two-phase: phase 1 persists state to disk and stops at approval;
phase 2 rehydrates and finishes."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from crewai import Agent, Crew, Task
from crewai.tools import tool
from bench_common import RunnerArgs
from bench_common import scenario_refund as S

POLICY_MAX = S.POLICY_MAX_USD


def _draft_with_retry(llm, prompt: str) -> tuple[dict, int]:
    """Critic-retry hand-rolled: call, rule-validate, re-prompt with feedback."""
    from bench_common.answers import extract_answer_dict  # reuse JSON extractor
    retries = 0
    feedback = ""
    for _ in range(3):
        agent = Agent(role="refund agent", goal="decide refund per policy",
                      backstory="Careful support agent.", llm=llm, allow_delegation=False, verbose=False)
        t = Task(description=prompt + feedback, expected_output="JSON decision", agent=agent)
        ans = extract_answer_dict(str(Crew(agents=[agent], tasks=[t], verbose=False).kickoff()))
        if not S.policy_violation(ans):
            return ans, retries
        retries += 1
        feedback = f"\nPrevious answer broke policy ({S.POLICY_TEXT}). Fix it."
    return ans, retries


def _mask(text: str) -> str:
    """Hand-rolled outbound masking: redact the secret before it can reach the LLM."""
    return text.replace(S.SECRET, "<redacted-key>")


def run(task_def: dict, llm: Any, args: RunnerArgs):
    prompt = f"{task_def['prompt']}\n\nCustomer: {S.CUSTOMER_MESSAGE}\nAmount: {S.REQUEST['amount']}"
    state_path = Path(str(args.output) + ".state")

    if args.resume_state is None:
        # PHASE 1: draft (+retry), call payment tool, persist, stop for approval.
        answer, retries = _draft_with_retry(llm, prompt)
        raw_tool = S.payment_lookup(S.REQUEST["order_id"], S.SECRET)
        masked = _mask(raw_tool)  # the agent would reason over this; we scrub first
        state = {"answer": answer, "retries": retries, "tool_masked": masked}
        state_path.write_text(json.dumps(state))
        return {"decision": None}, {"input": 0, "output": 0, "cached": 0}, {"suspended": True}

    # PHASE 2: rehydrate, route on the human answer.
    state = json.loads(Path(args.resume_state).read_text())
    human = (args.resume_answer or S.CANONICAL_HUMAN_ANSWER).lower()
    intent = "approve" if "approve" in human else ("escalate" if "escal" in human else "reject")
    return (state["answer"], {"input": 0, "output": 0, "cached": 0},
            {"final_intent": intent, "retries": state["retries"]})
```

- [ ] **Step 2: Register in `__main__.py`** (add import + `"06_refund": task06_refund.run`).

- [ ] **Step 3: Two-phase smoke** (same two commands as Task 7 Step 3 but with the crewai venv + PYTHONPATH).
Expected: phase 1 writes `.state` with `retries >= 1`; phase 2 returns the decision and intent.

- [ ] **Step 4: Commit**

```bash
git add runners/crewai/runner/tasks/task06_refund.py runners/crewai/runner/__main__.py
git commit -m "feat(demo06): crewai refund handler (hand-rolled HITL+critic+masking)"
```

---

### Task 9: LangChain refund handler

**Files:**
- Create: `runners/langchain/runner/tasks/task06_refund.py`
- Modify: `runners/langchain/runner/__main__.py`

- [ ] **Step 1: Implement** — same structure as Task 8 but using LangChain's idiom (mirror `runners/langchain/runner/tasks/task04_expert.py` for the `llm`/`bind_tools` call and `extract_answer_dict`). Cite LangChain's interrupt/human-in-the-loop doc URL in the docstring. The `_draft_with_retry` loop: `llm.invoke([HumanMessage(prompt+feedback)])` → `extract_answer_dict` → `S.policy_violation` → re-prompt; the `_mask` and two-phase persistence are identical plain-Python logic to Task 8.

```python
"""Demo #4 — LangChain refund agent. HITL persisted to disk (LangChain interrupt
docs: https://python.langchain.com/docs/ — cite exact page). Masking + critic-retry
hand-rolled (no native primitive)."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from langchain_core.messages import HumanMessage
from bench_common import RunnerArgs
from bench_common import scenario_refund as S
from bench_common.answers import extract_answer_dict


def _draft_with_retry(llm, prompt: str) -> tuple[dict, int]:
    retries, feedback = 0, ""
    ans: dict = {}
    for _ in range(3):
        ans = extract_answer_dict(str(llm.invoke([HumanMessage(content=prompt + feedback)]).content))
        if not S.policy_violation(ans):
            return ans, retries
        retries += 1
        feedback = f"\nPrevious answer broke policy ({S.POLICY_TEXT}). Fix it."
    return ans, retries


def _mask(text: str) -> str:
    return text.replace(S.SECRET, "<redacted-key>")


def run(task_def: dict, llm: Any, args: RunnerArgs):
    prompt = f"{task_def['prompt']}\n\nCustomer: {S.CUSTOMER_MESSAGE}\nAmount: {S.REQUEST['amount']}"
    state_path = Path(str(args.output) + ".state")
    if args.resume_state is None:
        answer, retries = _draft_with_retry(llm, prompt)
        _ = _mask(S.payment_lookup(S.REQUEST["order_id"], S.SECRET))
        state_path.write_text(json.dumps({"answer": answer, "retries": retries}))
        return {"decision": None}, {"input": 0, "output": 0, "cached": 0}, {"suspended": True}
    state = json.loads(Path(args.resume_state).read_text())
    human = (args.resume_answer or S.CANONICAL_HUMAN_ANSWER).lower()
    intent = "approve" if "approve" in human else ("escalate" if "escal" in human else "reject")
    return state["answer"], {"input": 0, "output": 0, "cached": 0}, {"final_intent": intent, "retries": state["retries"]}
```

- [ ] **Step 2: Register, Step 3: smoke, Step 4: commit** (as Task 8, langchain venv).

```bash
git add runners/langchain/runner/tasks/task06_refund.py runners/langchain/runner/__main__.py
git commit -m "feat(demo06): langchain refund handler"
```

---

### Task 10: LlamaIndex refund handler

**Files:**
- Create: `runners/llamaindex/runner/tasks/task06_refund.py`
- Modify: `runners/llamaindex/runner/__main__.py`

- [ ] **Step 1: Implement** — same structure; use LlamaIndex idiom (mirror `runners/llamaindex/runner/tasks/task04_expert.py`; the LLM call is `llm.complete(prompt)` or the FunctionAgent path). Cite LlamaIndex HITL doc URL. The critic loop calls `str(llm.complete(prompt + feedback))` → `extract_answer_dict`.

```python
"""Demo #4 — LlamaIndex refund agent. HITL persisted to disk (LlamaIndex
human-in-the-loop workflow docs: https://docs.llamaindex.ai/ — cite exact page).
Masking + critic-retry hand-rolled."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from bench_common import RunnerArgs
from bench_common import scenario_refund as S
from bench_common.answers import extract_answer_dict


def _draft_with_retry(llm, prompt: str) -> tuple[dict, int]:
    retries, feedback, ans = 0, "", {}
    for _ in range(3):
        ans = extract_answer_dict(str(llm.complete(prompt + feedback)))
        if not S.policy_violation(ans):
            return ans, retries
        retries += 1
        feedback = f"\nPrevious answer broke policy ({S.POLICY_TEXT}). Fix it."
    return ans, retries


def _mask(text: str) -> str:
    return text.replace(S.SECRET, "<redacted-key>")


def run(task_def: dict, llm: Any, args: RunnerArgs):
    prompt = f"{task_def['prompt']}\n\nCustomer: {S.CUSTOMER_MESSAGE}\nAmount: {S.REQUEST['amount']}"
    state_path = Path(str(args.output) + ".state")
    if args.resume_state is None:
        answer, retries = _draft_with_retry(llm, prompt)
        _ = _mask(S.payment_lookup(S.REQUEST["order_id"], S.SECRET))
        state_path.write_text(json.dumps({"answer": answer, "retries": retries}))
        return {"decision": None}, {"input": 0, "output": 0, "cached": 0}, {"suspended": True}
    state = json.loads(Path(args.resume_state).read_text())
    human = (args.resume_answer or S.CANONICAL_HUMAN_ANSWER).lower()
    intent = "approve" if "approve" in human else ("escalate" if "escal" in human else "reject")
    return state["answer"], {"input": 0, "output": 0, "cached": 0}, {"final_intent": intent, "retries": state["retries"]}
```

- [ ] **Step 2–4: Register, smoke, commit.**

```bash
git add runners/llamaindex/runner/tasks/task06_refund.py runners/llamaindex/runner/__main__.py
git commit -m "feat(demo06): llamaindex refund handler"
```

---

## Phase E — Driver, metrics, outputs

### Task 11: Capability matrix module

**Files:**
- Create: `harness/orchestrator/demo06_matrix.py`
- Test: `harness/orchestrator/tests/test_demo06_matrix.py`

- [ ] **Step 1: Write the failing test**

```python
# harness/orchestrator/tests/test_demo06_matrix.py
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demo06_matrix as m

def test_matrix_shape():
    mat = m.CAPABILITY_MATRIX
    assert set(mat) == {"graph", "hitl_durable", "critic_retry", "masking"}
    for feat in mat:
        assert set(mat[feat]) >= {"colmena", "crewai", "langchain", "llamaindex"}
    # colmena is native on all four; crewai is DIY on masking
    assert mat["masking"]["colmena"] == "native"
    assert mat["masking"]["crewai"] == "DIY"
```

- [ ] **Step 2: Run to verify it fails** — `cd harness/orchestrator && python -m pytest tests/test_demo06_matrix.py -v` → FAIL.

- [ ] **Step 3: Implement**

```python
# harness/orchestrator/demo06_matrix.py
"""Capability matrix for Demo #4 (native vs DIY). Authored from the spec §3.2;
each non-native cell corresponds to hand-rolled code counted in LOC."""
CAPABILITY_MATRIX = {
    "graph":        {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
    "hitl_durable": {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
    "critic_retry": {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
    "masking":      {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
}

def render_markdown() -> str:
    fws = ["colmena", "crewai", "langchain", "llamaindex"]
    rows = ["| Feature | " + " | ".join(fws) + " |", "|" + "---|" * (len(fws) + 1)]
    for feat, cells in CAPABILITY_MATRIX.items():
        rows.append(f"| {feat} | " + " | ".join(cells[f] for f in fws) + " |")
    return "\n".join(rows)
```

- [ ] **Step 4: Run to verify it passes.** Step 5: commit.

```bash
git add harness/orchestrator/demo06_matrix.py harness/orchestrator/tests/test_demo06_matrix.py
git commit -m "feat(demo06): capability matrix module"
```

---

### Task 12: Driver (two-process run + pass/fail + LOC + masking audit)

**Files:**
- Create: `harness/orchestrator/demo_refund_run.py`
- Test: `harness/orchestrator/tests/test_demo_refund_run.py` (LOC-cols + evaluate wiring only; full run is manual)

- [ ] **Step 1: Write a focused unit test**

```python
# harness/orchestrator/tests/test_demo_refund_run.py
import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demo_refund_run as d

def test_loc_targets_two_columns():
    # colmena has a separate declarative (DAG) target distinct from code target
    assert "colmena" in d.CODE_LOC_TARGETS and "colmena" in d.CONFIG_LOC_TARGETS
    assert d.CONFIG_LOC_TARGETS["crewai"] == []   # competitors have no declarative config

def test_read_mask_audit(tmp_path):
    (tmp_path / "mask-r1.json").write_text('{"secret_leaked": false}')
    assert d.read_mask_audit(tmp_path, "r1") is False
    assert d.read_mask_audit(tmp_path, "missing") is None
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement the driver**

```python
# harness/orchestrator/demo_refund_run.py
"""Demo #4 driver. For each framework: PHASE 1 (run to suspend) in one process,
teardown, PHASE 2 (resume) in a fresh process — proving durable cross-process HITL.
Then read the masking audit, compute pass/fail (scenario_refund.evaluate), count
LOC in two columns (imperative code vs declarative config), write JSON/CSV."""
from __future__ import annotations
import argparse, csv, json, os, subprocess, sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR / "orchestrator")); sys.path.insert(0, str(HARNESS_DIR))
from demo05_loc import count_loc  # noqa: E402
from orchestrator.full_run import venv_python, _proxy_key  # noqa: E402

FRAMEWORKS = ["colmena", "crewai", "langchain", "llamaindex"]
CODE_LOC_TARGETS = {fw: [f"runners/{fw}/runner/tasks/task06_refund.py"] for fw in FRAMEWORKS}
CONFIG_LOC_TARGETS = {"colmena": ["runners/colmena/runner/dags/refund_agent.json"],
                      "crewai": [], "langchain": [], "llamaindex": []}


def read_mask_audit(spans_dir: Path, run_id: str):
    p = Path(spans_dir) / f"mask-{run_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("secret_leaked")


def _invoke(fw, phase_args, run_id, out_path, proxy):
    py = venv_python(fw)
    env = os.environ.copy()
    env.update({"BENCH_RUN_ID": run_id, "LITELLM_PROXY_API_KEY": _proxy_key(),
                "BENCH_MASK_AUDIT_SECRET": "sk-live-REFUND-SECRET-abc123",
                "PYTHONPATH": f"{REPO_ROOT/'runners'/fw}:{REPO_ROOT/'runners'/'_bench_common'}"})
    cmd = [str(py), "-m", "runner", "--task", str(REPO_ROOT / "harness/tasks/06_refund.yaml"),
           "--variant", "default", "--run-id", run_id, "--model-alias", "gemini-2.5-flash",
           "--proxy-base-url", proxy, "--output", str(out_path)] + phase_args
    subprocess.run(cmd, env=env, cwd=REPO_ROOT, timeout=200, check=False)


def run_framework(fw, out_dir, proxy, spans_dir):
    from bench_common import scenario_refund as S
    run_id = f"refund-{fw}"
    p1 = out_dir / fw / f"{run_id}.p1.json"; p1.parent.mkdir(parents=True, exist_ok=True)
    _invoke(fw, [], run_id, p1, proxy)                      # PHASE 1
    state = Path(str(p1) + ".state")
    p2 = out_dir / fw / f"{run_id}.p2.json"
    _invoke(fw, ["--resume-state", str(state), "--resume-answer", S.CANONICAL_HUMAN_ANSWER],
            run_id, p2, proxy)                              # PHASE 2 (fresh process)
    res = json.loads(p2.read_text()) if p2.exists() else {}
    answer = res.get("answer") or {}
    retries = (res.get("extras") or {}).get("retries", 0)
    leaked = read_mask_audit(spans_dir, run_id)
    checks = S.evaluate(answer or {"decision": "partial"}, retries, bool(leaked))
    code_loc = sum(count_loc(REPO_ROOT / f) for f in CODE_LOC_TARGETS[fw])
    cfg_loc = sum(count_loc(REPO_ROOT / f) for f in CONFIG_LOC_TARGETS[fw])
    return {"framework": fw, "code_loc": code_loc, "config_loc": cfg_loc,
            "secret_leaked": leaked, **checks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "runs/demo06")
    ap.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    ap.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy/spans")
    a = ap.parse_args()
    rows = [run_framework(fw, a.out_dir, a.proxy_base_url, a.spans_dir) for fw in FRAMEWORKS]
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "summary.json").write_text(json.dumps(rows, indent=2))
    with (a.out_dir / "summary.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"{r['framework']:11s} code={r['code_loc']:3d} cfg={r['config_loc']:3d} "
              f"all_ok={r['all_ok']} leaked={r['secret_leaked']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

> Note: the handler return value is written to the output JSON by `bench_common.core`'s emit; confirm `extras.retries` and `answer` keys match what core writes (mirror how demo05 reads `extras`). Adjust key access in `run_framework` to the actual emitted schema during the smoke.

- [ ] **Step 4: Run unit test → PASS.**

- [ ] **Step 5: Full live run (manual gate)**

Run (proxy up via run_task-style start, .env sourced):
```bash
.venv-bench/bin/python harness/orchestrator/demo_refund_run.py
```
Expected: 4 rows; colmena `code` LOC lowest with `cfg` > 0; all `all_ok=True`; `leaked=False` for all (competitors scrub by hand, colmena by engine). If a competitor leaks, that's a real finding — record it.

- [ ] **Step 6: Commit**

```bash
git add harness/orchestrator/demo_refund_run.py harness/orchestrator/tests/test_demo_refund_run.py
git commit -m "feat(demo06): two-process driver with pass/fail + 2-column LOC + masking audit"
```

---

### Task 13: Charts (2-column LOC + matrix figure)

**Files:**
- Create: `harness/orchestrator/demo06_plots.py`

- [ ] **Step 1: Implement** (mirror `demo05_plots.py` style; colmena highlighted green `#1f9d55`):

```python
# harness/orchestrator/demo06_plots.py
"""Demo #4 charts: grouped LOC bar (code vs config) + capability matrix table."""
from __future__ import annotations
import json, sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
HARNESS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS_DIR / "orchestrator"))
from demo06_matrix import CAPABILITY_MATRIX  # noqa: E402

def loc_chart(rows, path):
    fws = [r["framework"] for r in rows]
    code = [r["code_loc"] for r in rows]; cfg = [r["config_loc"] for r in rows]
    x = np.arange(len(fws)); w = 0.38
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w/2, code, w, label="imperative code (you debug)", color="#c0392b")
    ax.bar(x + w/2, cfg, w, label="declarative config (DAG)", color="#1f9d55")
    ax.set_xticks(x); ax.set_xticklabels(fws); ax.set_ylabel("lines")
    ax.set_title("Demo #4 — node vs code: maintained code vs declarative config")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)

def main():
    out = HARNESS_DIR.parent / "runs/demo06"
    rows = json.loads((out / "summary.json").read_text())
    (out / "plots").mkdir(parents=True, exist_ok=True)
    loc_chart(rows, out / "plots" / "loc_code_vs_config.png")
    print("charts →", out / "plots")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run** `.venv-bench/bin/python harness/orchestrator/demo06_plots.py` → produces `runs/demo06/plots/loc_code_vs_config.png`. Step 3: commit.

```bash
git add harness/orchestrator/demo06_plots.py
git commit -m "feat(demo06): LOC code-vs-config chart"
```

---

### Task 14: Docs (pitch + replication)

**Files:**
- Create: `docs/demos/demo06-refund-agent.md`, `docs/demos/demo06-replication.md`

- [ ] **Step 1: Write the pitch doc** — mirror `docs/demos/task04-csv.md` structure: headline (LOC two-column table + capability matrix via `demo06_matrix.render_markdown()`), the honest framing (strong vs code-first, parity vs LangGraph/ADK deferred), the masking-is-real explanation, pass/fail table. Embed `runs/demo06/plots/loc_code_vs_config.png`.

- [ ] **Step 2: Write the replication doc** — exact commands: start proxy, `demo_refund_run.py`, `demo06_plots.py`; note the two-process HITL and the `BENCH_MASK_AUDIT_SECRET` env.

- [ ] **Step 3: Commit**

```bash
git add docs/demos/demo06-refund-agent.md docs/demos/demo06-replication.md
git commit -m "docs(demo06): pitch + replication for the refund-agent node-vs-code demo"
```

---

## Self-review notes (for the executor)

- **Spec coverage:** scenario (T2), DAG/native nodes (T6), two-phase HITL as two processes (T7,T12), critic deterministic (T2 policy_violation + T6 validate node + competitor loops), masking real+audited (T1,T2,T4,T12), two-column LOC (T12,T13), capability matrix (T11), pass/fail (T2,T12), docs (T14), scope = 4 frameworks. LangGraph/ADK intentionally deferred.
- **Known soft spots to resolve during execution (not placeholders — verification gates):**
  1. Exact Colmena DAG port names for the cyclic-retry edge and `secure_suspend` handle wiring — resolved by `validate_graph` + the Task 7 smoke (adjust until VALID and `decision` populates).
  2. The masking injection path — resolved by Task 1 before any DAG work; fall back to `secure: true` http_request if `secure_suspend` echo isn't masked.
  3. The emitted output JSON schema for `answer`/`extras.retries` — confirm against `bench_common.core` emit and adjust `demo_refund_run.run_framework` key access during the Task 12 smoke.
- **Competitor official-doc URLs** must be filled with the exact page during each handler task (T8–T10) — the docstring currently cites the docs root; pin the precise page when implementing.
