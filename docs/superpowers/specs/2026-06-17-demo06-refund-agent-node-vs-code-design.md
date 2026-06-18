# Demo #4 — "Node vs Code": a production-hardened refund agent

**Status:** design approved 2026-06-17 · **Topic owner:** daniel@startti.co
**Type:** hero demo (the node-vs-code win) · **Bench task id:** `06_refund` (Demo #4)

---

## 1. Goal & thesis

Sell Colmena on **node-vs-code**: the *same* production-hardened agent is, in
Colmena, a **declarative DAG (~90 lines of JSON, which does not count as code)** +
a thin runner; in the code-first frameworks it is **hundreds of lines of maintained
imperative code** that hand-rolls HITL persistence, a critic-retry loop, and
outbound secret masking.

**Honest framing (from `colmena-real-differentiators` memory):** this is strong vs
the three code-first frameworks (CrewAI, LangChain, LlamaIndex) and near-parity vs
graph frameworks (LangGraph, ADK). The pitch is the **bundled production-hardening**
(durable HITL + critic-retry + masking as first-class nodes), NOT "it's a graph."
Two features — durable cross-process suspend/resume and outbound secret masking —
remain hand-rolled code even in LangGraph/ADK; that is where the win survives
scrutiny.

**Scope, round 1:** Colmena + CrewAI + LangChain + LlamaIndex. LangGraph + ADK are
a second round (they reach parity on "it's a graph", so they're added once the
method and the round-1 win are validated).

---

## 2. Scenario — refund support agent

A customer requests a refund; the agent decides, validates against policy, uses a
secret payment-API key, and a human approves before money moves. Identical flow for
all frameworks:

```
1. trigger           receives {order_id, reason, amount}
2. llm_call (draft)  decides refund (approve / partial / reject) + justification
3. validate (critic) checks policy (amount <= limit, required fields, tone)
        └─ on fail → cyclic edge back to draft with feedback (max 3 iterations)
4. tool: payment API looks up the order using a SECRET api key   ← MASKING: the key
        (secure:true)     never appears in any LLM-bound message
5. suspend (HITL)    human approves the refund (durable: process actually stops)
6. router (intent)   approve / escalate / reject from the free-text human answer
7. log / action      issue / escalate / decline
```

Three differentiators exercised: **masking** (step 4), **critic-retry** (step 3),
**durable HITL + routing** (steps 5–6).

---

## 3. Comparison method

Three axes; everything that could bias the result is shared across frameworks.

### 3.1 LOC (primary metric — node-vs-code)
Count maintained imperative code with the existing counter
(`harness/orchestrator/demo05_loc.py`), same rules as Demo 05:
- **Colmena:** the DAG JSON is **declarative config, shown separately, NOT counted**;
  only the thin runner Python counts.
- **Competitors:** the full handler that implements HITL persistence, the
  critic-retry loop, masking, and routing — all counts.
- Prompt strings are not counted as code (shared content), per existing rules.

### 3.2 Capability matrix (native vs DIY)
| Feature | Colmena | CrewAI | LangChain | LlamaIndex |
|---|---|---|---|---|
| Graph / branching | node | DIY | DIY | DIY |
| HITL suspend/resume (durable, cross-process) | `suspend` node | DIY | DIY | DIY |
| Critic-retry | cyclic edge / `critic` node | DIY | DIY | DIY |
| Outbound secret masking | engine (`secure:true`) | DIY | DIY | DIY |

### 3.3 Functional pass/fail (so LOC is not theater)
Each framework must actually pass the same checks (see §6).

### 3.4 Fairness rules
- Each competitor feature is implemented **by hand, idiomatic, minimal-but-complete**
  — the least code that makes the feature genuinely work (no strawman, no over-build).
- The shared scenario assets (customer message, policy, mock payment tool, the
  secret, the canonical human answer, the pass/fail checks) are byte-identical.
- Same model, temperature, and proxy for all (`gemini-2.5-flash`, temp 0).
- The capability matrix annotates which features were native vs hand-rolled, so LOC
  and "free vs you-wrote-it" are read together.

---

## 4. Colmena DAG (`refund_agent.json`)

One declarative graph using native node types (verified node inventory in
`registry.rs`):
- `trigger_webhook` / `mock_input` → entry
- `llm_call` → draft refund decision
- validator: `python_script` (or `router` rule-mode) checking policy; on fail a
  `cyclic: true` edge back to `llm_call` with `max_total_calls` as the retry cap
- payment tool: tool node with `secure: true`; the secret is a secure value, injected
  at execution and masked outbound by the engine (`mask_outbound`,
  `dag_tool_executor.rs:1773`)
- `suspend` → human approval (question id e.g. `approve_refund`)
- `router` (extract_and_route over free text) → `approve` / `escalate` / `reject`
- `log` nodes → terminal actions

The critic-retry uses the cyclic-subgraph pattern (single-LLM flow). Colmena also
ships a dedicated `critic` node inside the `orchestrator` construct; we note it in
the matrix as an even-more-bundled option but use the cyclic pattern to keep the DAG
focused and apples-to-apples with the competitors.

---

## 5. HITL two-phase protocol (VERIFIED LIVE 2026-06-17)

The bench drives the human approval automatically as a two-phase call. Verified with
a live `input→suspend→log` smoke.

```
PHASE 1: run_dag(graph, None, None, payload, True, agent_session_id="run_xyz")
  → on suspend returns:
    { "__colmena_status": "SUSPENDED",
      "questions": [ { "id": "approve_refund", ... } ],
      "session_id": "<UUID>" }            # <UUID> is the resume_id

PHASE 2: run_dag(graph,
                 resume_id     = "<UUID from phase 1>",
                 resume_answer = "A[approve_refund]: yes, approve",   # Q[id]/A[id] format
                 payload, True,
                 agent_session_id = "run_xyz")    # the ORIGINAL id, not the UUID
  → completes: { "controller": {"status":"resumed","answer_received":"..."}, ... }
```

**Non-obvious rules the implementation MUST honor (discovered during verification):**
1. `resume_id` is the `session_id` **returned by phase 1** (an engine UUID), not the
   id you passed in.
2. On phase 2, `agent_session_id` must be the **original** id, not the resume_id.
3. Use a **unique `agent_session_id` per run** — concurrent suspended chains under
   the same id raise "Found N concurrent suspended chains … not supported".
4. `resume_answer` uses the canonical ID-keyed format `A[<id>]: <answer>` (parser in
   `qa_response_parser.rs`); a plain string fails with "missing answer for id".

Competitors implement the same two-phase contract (run → persist state → resume),
which is the durable-HITL code that counts toward their LOC.

---

## 6. Verification (pass/fail, per framework)

- **HITL:** phase 1 suspends; phase 2 with the canonical answer completes the run.
- **Critic-retry:** a deliberately bad first draft (refund amount over the policy
  limit) triggers ≥1 retry; the final decision satisfies policy.
- **Masking (provider-authoritative):** the proxy captures the `messages` of every
  request (gated by an env var, only for this demo) and we assert the secret string
  `sk-live-REFUND-…` **never** appears in any LLM-bound body. This is the only
  trustworthy masking test because the proxy is the single chokepoint that sees what
  actually reaches the model (same philosophy as token counting).

---

## 7. Metrics & outputs

- LOC per framework (`demo05_loc.py`), Colmena lowest; DAG line count shown
  separately and labeled "declarative config, not code".
- Capability matrix (authored, §3.2).
- Pass/fail table per feature per framework.
- Charts: LOC bar (Colmena highlighted) + the matrix rendered as a table/figure.
- All raw results saved as JSON/CSV (consistent with Demo 05 / Task 4) so the pitch
  artifacts regenerate without re-running.

---

## 8. File layout

- `runners/_bench_common/bench_common/scenario_refund.py` — shared assets (message,
  policy, mock payment tool, secret, canonical answer, pass/fail checks)
- `runners/colmena/runner/dags/refund_agent.json` — the DAG (config, not LOC)
- `runners/colmena/runner/tasks/task06_refund.py` — thin Colmena runner (two-phase)
- `runners/{crewai,langchain,llamaindex}/runner/tasks/task06_refund.py` — competitor
  handlers (hand-rolled HITL + critic-retry + masking)
- `harness/tasks/06_refund.yaml` — task definition
- `harness/orchestrator/demo_refund_run.py` — driver (two-phase, pass/fail, LOC,
  masking scan, JSON/CSV + charts)
- `proxy/spans_callback.py` — add an opt-in request-body capture mode for the masking
  audit
- `docs/demos/demo06-refund-agent.md` + replication doc — pitch + repro

---

## 9. Risks / open items

- **Masking end-to-end not yet smoke-tested live.** The engine code and fixtures
  exist and the secret is injected via the same (now-verified) resume mechanism, but
  a tool-node + secure-value + proxy-scan smoke is the **first verifiable step of the
  implementation plan**. If non-interactive secure-value seeding is awkward, fall
  back to providing the secret via a `secure_suspend` resume (reuses the verified
  two-phase path).
- **Competitor "minimal-but-complete" is a judgment call.** Mitigation: each
  competitor implementation must pass the identical §6 checks; we count the least
  code that passes, and disclose the approach in the matrix.
- **LangGraph/ADK deferred.** Round-2; the matrix and chart are built to extend to 6.

---

## 10. Out of scope (round 1)
- LangGraph and ADK implementations.
- Real payment provider / real email — the payment tool is a deterministic mock.
- Token/cost as a headline (this demo is about code + bundled capability, not tokens;
  tokens may be captured for completeness but are not the pitch).
