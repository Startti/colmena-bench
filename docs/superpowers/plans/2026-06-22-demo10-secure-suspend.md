# Demo #10 — `secure_suspend` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that collecting K=3 credentials mid-conversation is one declarative `secure_suspend` node in Colmena (encrypted, handles-only to the LLM, auto-injected into a downstream HTTP call) while the idiomatic competitor approach leaks the secret into the LLM transcript.

**Architecture:** A two-phase (suspend→resume) Colmena DAG modeled on Demo #6's proven `refund_agent.json` (which already uses `secure_suspend` as a tool + auto-injection): an `llm_call` with `secure_suspend_allowed`-style tool that collects 3 secrets in one batch, then calls an `http_request` tool whose handles are auto-replaced with real values before hitting a local **mock** endpoint. Competitors collect the secrets in-conversation (leak). Leak is measured by the proxy's existing in-memory secret-audit; delivery by what the mock received.

**Tech Stack:** Python 3.11, Colmena PyO3 (`colmena.run_dag`, two-phase resume), LiteLLM proxy + `audit_messages_for_secret`, stdlib `http.server` mock, matplotlib, pytest.

**Spec:** [docs/superpowers/specs/2026-06-22-demo10-secure-suspend-design.md](../specs/2026-06-22-demo10-secure-suspend-design.md)

---

## File Structure

| File | Responsibility |
|---|---|
| `runners/_bench_common/bench_common/scenario_secrets.py` (**new**) | The 3 fake secrets + per-run MARKER, the onboarding prompt, the 3-secret Q/A resume payload builder, the leak/delivery/echo scorer, the mock-endpoint URL contract. |
| `runners/_bench_common/tests/test_scenario_secrets.py` (**new**) | Unit tests (marker-in-all-secrets, Q/A payload shape, scorer). |
| `harness/orchestrator/mock_account_api.py` (**new**) | Tiny stdlib `http.server` mock: records the received body to a file; `?echo=1` variant echoes the secret back in its response. |
| `runners/colmena/runner/dags/secrets_agent.json` (**new**) | Colmena DAG: `trigger → llm_call(secure_suspend tool collecting 3 + http tool to mock) → log`. |
| `runners/colmena/runner/tasks/task10_secrets.py` (**new**) | Colmena two-phase handler (clone of `task06_refund.py`; resume answers all 3 secrets in one payload). |
| `runners/{llamaindex,langchain,langgraph,crewai,google_adk}/runner/tasks/task10_secrets.py` (**new ×5**) | Naive handlers: collect 3 secrets in-conversation, then HTTP to the mock with real values. |
| `harness/orchestrator/demo_secrets_run.py` (**new**) | Two-phase driver (clone of `demo_refund_run.py`): starts mock, sets the leak-audit env, runs colmena two-phase + competitors single-phase, scores, writes `runs/demo10/summary.{json,csv}`. |
| `harness/orchestrator/demo10_matrix.py`, `demo10_plots.py` (**new**) | Capability matrix + leak-rate bar + LOC bar. |
| `harness/tasks/10_secrets.yaml`, `scripts/run_demo10.sh` (**new**) | Task descriptor + one-command run. |
| `runners/*/runner/__main__.py` (**modify ×6**) | Register `"10_secrets": task10_secrets.run`. |
| `docs/demos/demo10-secure-suspend.md`, `demo10-replication.md` (**new**) | Pitch + replication. |

**Reused as-is:** the proxy `audit_messages_for_secret` (leak detection), Demo #6's two-phase resume protocol (`task06_refund.py`), `demo_refund_run.py` (driver shape), `demo06_matrix.py`/`demo06_plots.py` (chart shape), `refund_agent.json` (DAG template — already does secure_suspend-as-tool + handle auto-injection).

**Conventions:** `_bench_common` tests run via `runners/_bench_common/.venv/bin/python -m pytest`. All secrets are FAKE; the mock is localhost; the proxy audit writes only a boolean. Frameworks: colmena + crewai, langchain, langgraph, llamaindex, google_adk.

---

## Task 0: DERISK — live end-to-end Colmena secure_suspend → http auto-injection

**Goal:** before building anything, prove the core flow live with a throwaay script: a Colmena DAG that collects 3 secrets via one `secure_suspend` tool, then calls an `http_request` tool to a local mock; confirm (a) phase-1 suspends, (b) one resume with all 3 answers continues, (c) the mock received the REAL secret values (auto-injection), (d) the proxy mask-audit shows `secret_leaked: false`.

**Files:** `scripts/_secrets_smoke.py` (throwaway; may delete after).

- [ ] **Step 1: Start a local mock** (stdlib) that writes the received body to `/tmp/d10_received.json`:

```python
# inline in the smoke script, or python -m http.server replacement:
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, threading
RECEIVED = {}
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length", 0)); body = self.rfile.read(n).decode()
        RECEIVED["body"] = body
        self.send_response(200); self.send_header("content-type","application/json"); self.end_headers()
        self.wfile.write(b'{"connected": true}')
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 8799), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
```

- [ ] **Step 2: Build a minimal DAG** (dict) modeled on `runners/colmena/runner/dags/refund_agent.json`'s `confirm` node — one `llm_call` with two tool_configurations:
  - `get_secrets`: `node_type: "secure_suspend"`, `node_schema.secrets.fixed` = a 3-element array `[{"name":"api_key","question":"Enter your API key"},{"name":"api_secret","question":"Enter your API secret"},{"name":"webhook_signing_secret","question":"Enter your webhook signing secret"}]`.
  - `connect_account`: `node_type: "http_request"`, `node_schema` with `base_url` fixed `http://127.0.0.1:8799`, `endpoint` fixed `/connect`, `method` fixed `POST`, and a `body`/fields carrying the 3 handles (the agent pastes the `<sv_*>` handles returned by get_secrets). Mark it so secure handles are injected (follow how refund's `pay` tool consumes the `<sv_...>` handle).
  - system_message: instruct the agent to (1) call get_secrets, (2) call connect_account passing the three returned `<sv_*>` handles verbatim, (3) report "connected".
  Set env like `task06_refund._ensure_env` (OPENAI_API_KEY, DATABASE_URL from COLMENA_DATABASE_URL, SECURE_VALUES_KEY, COLMENA_LOCAL_STORAGE_DIR).

- [ ] **Step 3: Run two-phase** with the proxy up and `BENCH_MASK_AUDIT_SECRET` set to a marker embedded in the 3 secret values. Phase 1: `colmena.run_dag(dag, None, None, {"prompt": "..."} , True, session_id)` → expect `__colmena_status == "SUSPENDED"`. Phase 2: resume with one payload answering all 3:
  `A[api_key]: ak-MARKER\nA[api_secret]: as-MARKER\nA[webhook_signing_secret]: wh-MARKER` (line-anchored Q/A, ids = the secret `name`s).

- [ ] **Step 4: Assert**
  - phase 1 suspended; the suspend `questions[]` lists `api_key, api_secret, webhook_signing_secret`.
  - after resume the run completes; `/tmp/d10_received.json` contains the REAL `ak-MARKER`/`as-MARKER`/`wh-MARKER` values (auto-injection worked).
  - `proxy/spans/mask-<run_id>.json` → `secret_leaked: false` (the MARKER never reached a prompt).

- [ ] **Step 5: Record findings** in the task report (exact suspend payload shape, the working `connect_account` http node_schema, whether all 3 secrets resume in one payload). If the http tool can't receive injected handles, document the exact wiring that does (mirror refund's `pay` secure tool). **Do not commit the throwaway** unless useful; capture the proven DAG shape for Task 3.

> If this DERISK fails, STOP and surface it — the rest of the demo depends on it. (This mirrors Demo #8's D8-T0.)

---

## Task 1: `scenario_secrets.py` — assets + scorer

**Files:** Create `runners/_bench_common/bench_common/scenario_secrets.py`; Test `runners/_bench_common/tests/test_scenario_secrets.py`.

- [ ] **Step 1: Write failing tests**

```python
import sys
from pathlib import Path
PKG = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(PKG))
from bench_common import scenario_secrets as ss

def test_three_secrets_all_carry_the_marker():
    s = ss.secrets()                       # {name: value}
    assert set(s) == {"api_key", "api_secret", "webhook_signing_secret"}
    for v in s.values():
        assert ss.MARKER in v              # auditing MARKER catches any of the 3 leaking

def test_resume_payload_answers_all_three_in_one_round_trip():
    p = ss.resume_payload()
    for name, val in ss.secrets().items():
        assert f"A[{name}]: {val}" in p     # one payload, all 3 ids

def test_score_secret_leaked_reads_mask_file(tmp_path):
    m = tmp_path / "mask-x.json"; m.write_text('{"secret_leaked": true}')
    assert ss.read_leaked(str(m)) is True
    assert ss.read_leaked(str(tmp_path / "nope.json")) is None   # missing -> not measured

def test_score_delivered_checks_all_three_real_values(tmp_path):
    rec = tmp_path / "rec.json"
    rec.write_text(__import__("json").dumps({"body": " ".join(ss.secrets().values())}))
    assert ss.delivered_to_api(str(rec)) is True
    rec.write_text('{"body": "<sv_api_key_xx> only handles here"}')
    assert ss.delivered_to_api(str(rec)) is False    # handles, not real values
```

- [ ] **Step 2: Run → FAIL** (`cd runners/_bench_common && .venv/bin/python -m pytest tests/test_scenario_secrets.py -v`).

- [ ] **Step 3: Implement**

```python
"""Demo #10 — secure_suspend scenario assets. All secrets are FAKE.

The 3 secrets share a per-import MARKER substring, so auditing the MARKER in the
proxy catches ANY of them leaking into an LLM prompt (the proxy audit takes one
needle). Delivery is verified by the mock recording the real values.
"""
from __future__ import annotations
import json, uuid
from pathlib import Path

MARKER = f"D10MARK-{uuid.uuid5(uuid.NAMESPACE_DNS, 'colmena-demo10')}"  # stable, fake

ONBOARDING_PROMPT = (
    "Connect the user's account to the payments provider. You do NOT have the "
    "credentials — you must ask the user for them, then call the connect endpoint. "
    "Collect the API key, API secret, and webhook signing secret, then connect."
)

def secrets() -> dict[str, str]:
    return {
        "api_key": f"ak-{MARKER}",
        "api_secret": f"as-{MARKER}",
        "webhook_signing_secret": f"wh-{MARKER}",
    }

def resume_payload() -> str:
    """One Q/A resume answering all 3 secret ids in a single round-trip."""
    s = secrets()
    return "\n".join(f"Q[{n}]: provide {n}\nA[{n}]: {v}" for n, v in s.items())

def read_leaked(mask_path: str):
    """True/False from the proxy mask-<run_id>.json; None if the file is absent."""
    p = Path(mask_path)
    if not p.exists():
        return None
    try:
        return bool(json.loads(p.read_text()).get("secret_leaked"))
    except Exception:
        return None

def delivered_to_api(received_path: str) -> bool:
    """True iff the mock received ALL three REAL secret values (not handles)."""
    p = Path(received_path)
    if not p.exists():
        return False
    blob = p.read_text()
    return all(v in blob for v in secrets().values())

def echo_leaked_from_text(text: str) -> bool:
    """True iff a real secret value appears in an LLM-visible text (echo path)."""
    return any(v in (text or "") for v in secrets().values())
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git add runners/_bench_common/bench_common/scenario_secrets.py runners/_bench_common/tests/test_scenario_secrets.py && git commit -m "feat(demo10): scenario_secrets assets + leak/delivery scorer"` (end body with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`).

---

## Task 2: mock account API

**Files:** Create `harness/orchestrator/mock_account_api.py`.

- [ ] **Step 1: Implement** a stdlib server with a `start_mock(port, record_path, echo)` returning a handle with `.stop()`:

```python
"""Demo #10 mock 'connect account' endpoint. Records the received body to
record_path; if echo=True, echoes the body back in the response (to exercise
outbound echo-masking)."""
from __future__ import annotations
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

def start_mock(port: int, record_path: str, echo: bool = False):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            body = self.rfile.read(n).decode("utf-8", "replace")
            with open(record_path, "w") as f:
                json.dump({"body": body}, f)
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
            payload = {"connected": True}
            if echo:
                payload["received"] = body   # echoes the secret back
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return srv  # caller does srv.shutdown()
```

- [ ] **Step 2: Test (no network races — use a fixed port + a real POST)**

```python
# runners/_bench_common/tests/test_mock_account_api.py  (or under harness tests)
def test_mock_records_and_echoes(tmp_path):
    import sys, json, urllib.request
    sys.path.insert(0, "harness")
    from orchestrator.mock_account_api import start_mock
    rec = tmp_path / "rec.json"
    srv = start_mock(8788, str(rec), echo=True)
    try:
        req = urllib.request.Request("http://127.0.0.1:8788/connect", data=b'{"api_key":"ak-X"}',
                                     headers={"content-type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req).read())
        assert resp["connected"] is True and "ak-X" in resp["received"]
        assert "ak-X" in json.loads(rec.read_text())["body"]
    finally:
        srv.shutdown()
```

- [ ] **Step 3: Run → PASS** (use whatever python runs the orchestrator, e.g. `.venv-bench/bin/python -m pytest`).
- [ ] **Step 4: Commit** — `git commit -m "feat(demo10): mock connect-account endpoint (record + echo variant)"`.

---

## Task 3: Colmena DAG + two-phase handler

**Files:** Create `runners/colmena/runner/dags/secrets_agent.json`, `runners/colmena/runner/tasks/task10_secrets.py`.

- [ ] **Step 1: Write the DAG** using the EXACT shapes Task 0 proved. Model on `refund_agent.json`'s `confirm` node: one `llm_call` with `get_secrets` (`node_type: secure_suspend`, `node_schema.secrets.fixed` = the 3-element array with names `api_key/api_secret/webhook_signing_secret`) and `connect_account` (`node_type: http_request`) pointing at `${BENCH_MOCK_URL}` (the handler substitutes the real localhost URL at runtime, like refund substitutes model/keys). The `connect_account` node_schema carries the 3 secret handles in its POST body (mirror how refund's `pay` consumes the `<sv_...>` handle so `inject_secrets` replaces them). system_message: call get_secrets, then connect_account passing the 3 `<sv_*>` handles verbatim, never echo a `<sv_*>`/secret. Edges: `trigger → assistant → log`.

- [ ] **Step 2: Write `task10_secrets.py`** by cloning `task06_refund.py` (same `_ensure_env`, `_is_suspended`, `_pending_question_ids`, `.state` file, two-phase structure) with these changes: phase-2 resume answers come from `scenario_secrets`: build a per-id answer map from `ss.secrets()` (so each pending id `api_key/api_secret/webhook_signing_secret` is answered with its real value); the DAG has only ONE suspend (the secure_suspend collecting all 3 in one shot), so a single resume with `ss.resume_payload()` clears it — but keep the defensive loop (read pending ids, answer each). Substitute `dag["nodes"]["assistant"]["config"]["model"]` and the mock URL (`BENCH_MOCK_URL` env) at runtime. `extras = {"arm":"colmena","received_path": os.environ["BENCH_MOCK_RECORD"], "round_trips": <count of resume calls>}`. Return zero usage.

- [ ] **Step 3: DAG-shape test** (no network) in `runners/_bench_common/tests/test_scenario_secrets.py`:

```python
def test_colmena_secrets_dag_has_3secret_suspend_and_http_tool():
    import json
    d = json.loads((PKG.parents[1] / "runners" / "colmena" / "runner" / "dags" / "secrets_agent.json").read_text())
    cfg = d["nodes"]["assistant"]["config"]; tc = cfg["tool_configurations"]
    sus = next(t for t in tc.values() if t.get("node_type") == "secure_suspend")
    names = [s["name"] for s in sus["node_schema"]["secrets"]["fixed"]]
    assert names == ["api_key", "api_secret", "webhook_signing_secret"]
    assert any(t.get("node_type") == "http_request" for t in tc.values())
```

- [ ] **Step 4: Run → PASS** + `ast.parse` the handler.
- [ ] **Step 5: Commit** — `git commit -m "feat(demo10): colmena secrets DAG (3-secret secure_suspend + http tool) + two-phase handler"`.

---

## Task 4: competitor naive handlers (×5)

**Files:** Create `runners/{llamaindex,langchain,langgraph,crewai,google_adk}/runner/tasks/task10_secrets.py`.

Each handler, mirroring its runner's `task06_refund.py` LLM wiring, runs a short conversation that **collects the 3 secrets in-conversation** then makes the HTTP call to the mock with the real values:
1. Turn 1: system + user = `ss.ONBOARDING_PROMPT`; the assistant asks for the credentials.
2. The driver feeds the user's reply = the 3 secret values (so they enter the message history — the leak).
3. The handler then POSTs the 3 real values to `os.environ["BENCH_MOCK_URL"]` (via the framework's http tool or a plain `urllib` call — the point is delivery + that the secrets were in the LLM transcript).
The handler returns `extras={"arm":"naive","received_path":...}` and zero usage. Because these frameworks send the `x-bench-run-id` header, the proxy audits their prompts → leak recorded.

- [ ] **Step 1–4 per framework:** copy the LLM client wiring from that runner's `task06_refund.py`; implement the collect-then-POST flow; `ast.parse` each. (No live unit test; validated in Task 6 smoke.)
- [ ] **Step 5: Commit** — `git commit -m "feat(demo10): naive collect-in-conversation handlers for 5 competitors"`.

---

## Task 5: driver `demo_secrets_run.py`

**Files:** Create `harness/orchestrator/demo_secrets_run.py` (clone `demo_refund_run.py`).

- [ ] **Step 1: Implement.** For each (framework, variant ∈ {collect, echo}):
  - Start the mock via `mock_account_api.start_mock(port, record_path=runs/demo10/received-<run_id>.json, echo=(variant=="echo"))`; set env `BENCH_MOCK_URL=http://127.0.0.1:<port>/connect`, `BENCH_MOCK_RECORD=<record_path>`, `BENCH_MASK_AUDIT_SECRET=ss.MARKER`, plus the proxy/PYTHONPATH/colmena-DB env from the refund driver.
  - **colmena**: two-phase (phase 1 to suspend → write `.state`; phase 2 resume with `ss.resume_payload()`), exactly like `demo_refund_run.py` drives the refund two-phase.
  - **competitors**: single invocation; the driver supplies the 3 secret values as the simulated user reply (env `BENCH_SECRET_REPLY=` the 3 values, consumed by the naive handler).
  - After the cell: `secret_leaked = ss.read_leaked(proxy/spans/mask-<run_id>.json)`; `delivered = ss.delivered_to_api(record_path)`; `echo_leaked` (echo variant) = `ss.read_leaked(...)` after the tool response returned (same audit catches the echoed secret re-entering the prompt); `round_trips` from colmena extras (else 1).
  - Write `runs/demo10/summary.{json,csv}`: rows `{framework, variant, secret_leaked, echo_leaked, delivered_to_api, round_trips, error}`.
  - Serial; one mock per cell; `srv.shutdown()` after each.

- [ ] **Step 2: `--help` + import smoke** (no live run). Confirm flags `--frameworks --variants --seeds`.
- [ ] **Step 3: Commit** — `git commit -m "feat(demo10): two-phase secrets driver + mock orchestration"`.

---

## Task 6: live smoke (gated) + register handlers + yaml + run script

**Files:** Modify 6 `runner/__main__.py`; Create `harness/tasks/10_secrets.yaml`, `scripts/run_demo10.sh`.

- [ ] **Step 1: Register** `task10_secrets` in all 6 runners' `__main__.py` (import + `"10_secrets": task10_secrets.run` in HANDLERS); `ast.parse` all 6.
- [ ] **Step 2: `10_secrets.yaml`** (model on `06_refund.yaml`): id `10_secrets`, variant `default` (or `collect`/`echo`), model_alias gemini-2.5-flash, the `prompt` = onboarding. Include a minimal `success` block (bench_common.run requires `task["success"]`).
- [ ] **Step 3: `run_demo10.sh`** (model on `run_demo06.sh`/`run_demo09.sh`): start managed proxy with `PROXY_BENCH_RUN_ID=demo10`, run `demo_secrets_run.py "$@"`, then `demo10_plots.py` (guarded). `bash -n` clean.
- [ ] **Step 4: Live smoke** with the proxy up:
  `bash scripts/run_demo10.sh --frameworks "colmena llamaindex" --variants collect --seeds 1`
  Expect in `runs/demo10/summary.json`: colmena `secret_leaked=false, delivered_to_api=true, round_trips=1`; llamaindex `secret_leaked=true, delivered_to_api=true`. Fix wiring (esp. colmena http-handle injection, mock URL) before the full run.
- [ ] **Step 5: Commit** — `git commit -m "feat(demo10): register handlers + yaml + run script + live smoke green"`.

---

## Task 7: matrix + charts + full run + docs

**Files:** Create `harness/orchestrator/demo10_matrix.py`, `demo10_plots.py`, `docs/demos/demo10-secure-suspend.md`, `demo10-replication.md`.

- [ ] **Step 1: `demo10_matrix.py`** (model on `demo06_matrix.py`): capability matrix rows = arms, columns = {durable pause, never-to-LLM by construction, AES-256 at rest, auto-inject downstream, echo-masking, LOC}. Colmena ✓ all (declarative); LangGraph ✓ durable-pause only; others ✗. LOC counted from each handler (reuse demo06's LOC counter if present).
- [ ] **Step 2: `demo10_plots.py`** (model on `demo06_plots.py`): (1) `leak_rate.png` — bar of `secret_leaked` + `echo_leaked` per framework (colmena 0, competitors 1); (2) `capability_matrix.png`; (3) `loc.png` declarative-vs-hand-rolled. Guard: exit 0 if summary missing.
- [ ] **Step 3: Full run** — `bash scripts/run_demo10.sh --frameworks "colmena crewai langchain langgraph llamaindex google_adk" --variants collect,echo --seeds 3`. Verify colmena: `secret_leaked=false` and `echo_leaked=false` across seeds; every competitor leaks (collect and/or echo); all `delivered_to_api=true`.
- [ ] **Step 4: Write docs** — `demo10-secure-suspend.md` (pitch: leak-vs-handle table from `summary.json`, capability matrix, echo-masking; honest stance — capability/counterfactual demo, LangGraph has durable pause, secrets fake/mock) + `demo10-replication.md` (exact commands, two-phase protocol, leak-audit mechanism, mock). Quote actual numbers.
- [ ] **Step 5: Commit** — `git commit -m "feat(demo10): matrix + charts + full 3-seed run + docs"`.

---

## Self-Review (plan author)

**1. Spec coverage:** §1 hypothesis → Tasks 3–5; §2 scenario/two-phase → Tasks 0,3,5; §3 three metrics (leak/delivered/round_trips) → Task 1 scorer + Task 5 driver; §3 capability matrix → Task 7; §4 echo-masking → Task 2 (echo mock) + Task 5 (echo variant) + Task 7 (row); §5 reuse → every task mirrors a named Demo #6 file; §6 DERISK → Task 0; §9 success criteria → Tasks 6–7. ✓
**2. Placeholder scan:** Task 3/4 say "mirror task06_refund.py" for the LLM/secure-tool wiring — these reference EXISTING committed files (not other plan tasks) and Task 0 proves the exact DAG shape first; concrete enough. No TBD/TODO.
**3. Type consistency:** `ss.MARKER`, `ss.secrets()->dict`, `ss.resume_payload()->str`, `ss.read_leaked(path)->bool|None`, `ss.delivered_to_api(path)->bool`, `ss.echo_leaked_from_text(str)->bool`, `start_mock(port,record_path,echo)->srv`, env `BENCH_MOCK_URL/BENCH_MOCK_RECORD/BENCH_MASK_AUDIT_SECRET/BENCH_SECRET_REPLY` — consistent across tasks. ✓

---

## Execution options
**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (Task 0 DERISK run by the controller, since it needs the live proxy/DB).
**2. Inline Execution** — batch with checkpoints.
