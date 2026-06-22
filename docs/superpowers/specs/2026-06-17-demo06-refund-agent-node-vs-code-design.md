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

### 3.1 LOC — TWO separate columns (decided 2026-06-17)
Report **two distinct numbers** for every framework, never collapsed into one, to
pre-empt the "the JSON IS the program" objection:
- **Imperative code lines** — maintained control-flow code you debug/test. Colmena's
  thin runner counts here; competitors' full handlers (HITL persistence, critic-retry
  loop, masking, routing) count here.
- **Declarative config lines** — Colmena's DAG JSON counts here; competitors typically
  have ~0. Shown alongside, labeled clearly as config, not hidden and not summed into
  the code column.

The pitch: even counting the JSON, Colmena is leaner, and its lines are *declarative
config you don't debug* rather than *imperative code you maintain*. Counting via
`harness/orchestrator/demo05_loc.py`.

**Pre-registered counting rule (identical for all 4):** exclude blank lines, comments,
and the shared bench-harness boilerplate that is byte-identical across frameworks
(the runner contract); count only agent-logic lines. Prompt strings are not code
(shared content). The same rule is applied mechanically by the counter, not by hand.

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
- Each competitor feature is implemented using **the pattern that framework's own
  official docs recommend** for HITL / retry / secret-handling, **with the doc URL
  cited in the handler**. The defense against "you inflated the competitor code" is
  not our judgment but the framework's own recommended idiom. Where the docs offer no
  pattern (e.g. outbound masking), that absence is itself the finding and the hand-
  rolled code is the honest cost — noted as DIY in the matrix.
- "Minimal-but-complete" still applies as a floor: the least idiomatic code that
  passes the identical §6 functional checks.
- The shared scenario assets (customer message, policy, mock payment tool, the
  secret, the canonical human answer, the pass/fail checks) are byte-identical.
- Same model, temperature, and proxy for all (`gemini-2.5-flash`, temp 0).
- The capability matrix annotates which features were native vs hand-rolled, so LOC
  and "free vs you-wrote-it" are read together.
- **Honest scenario framing:** the three features are universal production concerns
  (human approval, validation, secret handling), not a Colmena feature checklist; the
  doc states this explicitly.

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

- **HITL — tested as two SEPARATE OS processes (decided 2026-06-17).** The driver
  runs phase 1 in one process invocation, **tears it down**, then runs phase 2 in a
  fresh process that must rehydrate state from disk and complete. This actually proves
  durable cross-process suspend/resume rather than assuming it; the competitors'
  on-disk persistence code is therefore real and legitimately counted.
- **Critic-retry — deterministic trigger (decided 2026-06-17).** The policy check is
  **rule-based** (not an LLM critic) so it always catches a violation, and the
  scenario guarantees a first-draft violation (refund amount just over the policy
  limit). We assert ≥1 retry fired and the final decision satisfies policy. This tests
  that the framework can *express* a retry loop, evenly across all four — not model
  luck.
- **Masking — provider-authoritative, and the leak must be real (decided 2026-06-17).**
  The mock payment tool **echoes the auth token it was called with** in its response
  payload — exactly the kind of data a naive agent would forward to the LLM to reason
  over. So a naive implementation genuinely leaks; masking is non-trivial. Colmena
  masks it in the engine; each competitor must hand-scrub the tool result. Verification:
  the proxy, in audit mode, scans the `messages` of every request **in memory** and
  records only `{secret_leaked: bool}` per run — it **never writes the raw body to
  disk** (the secret would otherwise land in logs, ironic for a masking demo). Pass =
  the secret never appears in any LLM-bound message. The proxy is the single chokepoint
  that sees what actually reaches the model (same philosophy as token counting).

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

- **Masking confirmed 2026-06-17 via live `run_dag` smoke** — the working path is `secure_suspend` (collect `pay_key` via `A[pay_key]:` resume) → tool node with `secure: true` whose output echoes the key; `hash_output` replaced the echoed string with a `<value_N>` handle BEFORE the `llm_call` saw it (`pay.echo == "<value_1>"`, LLM summary contained no raw key, `RAW SECRET present: False`). NOTE: on the plain DAG-edge path `mask_outbound` does NOT run (only the LLM-tool-call dispatcher in `dag_tool_executor.rs` calls it); a `secure: true`-less tool node leaks the raw key into the LLM (verified). So the demo MUST set `secure: true` on the refund tool node and accept that `hash_output` masks the whole output field, not just the secret substring.
- **Competitor code fairness — RESOLVED to "official-doc idiom + cited" (§3.4).** Each
  competitor implementation also passes the identical §6 checks. Residual risk: a
  framework's docs may genuinely lack a HITL/masking pattern — that absence is reported
  as the finding, not papered over.
- **HITL durability — RESOLVED to two-process test (§6).** Risk: the bench harness
  must support a teardown-between-phases invocation model; the driver owns this.
- **Critic determinism — RESOLVED to rule-based check + guaranteed violation (§6).**
- **LangGraph/ADK deferred.** Round-2; the matrix and chart are built to extend to 6.

---

## 10. Out of scope (round 1)
- LangGraph and ADK implementations.
- Real payment provider / real email — the payment tool is a deterministic mock.
- Token/cost as a headline (this demo is about code + bundled capability, not tokens;
  tokens may be captured for completeness but are not the pitch).
