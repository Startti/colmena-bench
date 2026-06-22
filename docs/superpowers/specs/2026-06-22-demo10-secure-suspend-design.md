# Demo #10 — `secure_suspend` (Interactive Encrypted Secret Collection) — Design

**Status:** Draft for review
**Date:** 2026-06-22
**Author:** daniel + Claude
**Pairs with:** Demo #9 (Skills) — the second of the next whitepaper tranche.

---

## 1. Hypothesis

> **Collecting K credentials mid-conversation is ONE declarative node in Colmena
> (`secure_suspend`): encrypted AES-256, only opaque `<sv_*>` handles reach the LLM,
> auto-injected into the downstream request — the secret NEVER touches a prompt. A
> competitor collecting the secret the idiomatic way (asking for it in the conversation)
> leaves it in the transcript → the LLM sees it → leak.**

This is a **capability + counterfactual** demo (like masking / HITL in Demo #6), NOT a
metric sweep. Security is Colmena's proven suit. The win is a clean binary: *did the secret
reach the model?*

### Honesty stance
- LangGraph **does** have durable HITL (`interrupt()`) — stated explicitly in the matrix.
  The point is that even with `interrupt()`, keeping the secret out of state + encrypting
  it + auto-injecting downstream + masking echoes is all hand-rolled, and the *idiomatic*
  mid-conversation collection leaks.
- All secrets are **fake**; the authenticated endpoint is a **mock**; zero real credentials
  anywhere (same posture as Demo #8's canary and Demo #6's planted secret).
- We do not claim a metric/throughput win — we claim a *guarantee* win (no leak, by
  construction, declaratively).

---

## 2. Scenario — API onboarding ("connect your account")

The agent must connect the user's account by calling a **mock authenticated endpoint**. It
needs **K = 3 secrets** that do not exist at deploy time — `api_key`, `api_secret`,
`webhook_signing_secret` — so it must ask the human mid-flow.

- **Colmena (hero):** an `llm_call` with `secure_suspend_allowed: true` + an `http_request`
  tool pointed at the mock. The agent calls the synthetic `ask_secret` tool → the DAG
  **suspends** → the human supplies all 3 secrets in **one resume round-trip** (canonical
  Q/A format) → AES-256 encrypted into `secure_value_mappings` → the agent sees only
  `<sv_*>` handles → when it calls the http tool with those handles, `inject_secrets`
  replaces them with the real values at execution time → the mock receives the real secret.
  This is a **two-phase run** (suspend + resume).
- **Competitors (naive idiomatic):** no durable encrypted-suspend; the idiomatic way to get
  a secret mid-conversation is to ask for it in the chat → the user's reply enters the
  message history → on the next LLM turn it is in the prompt → **leak**.

---

## 3. The three arms / what we measure (all binary, objective)

Per (framework, variant) cell:

1. **`secret_leaked` (the hero):** did any planted secret appear in any message sent to the
   LLM? Measured by the proxy's in-memory audit (`audit_messages_for_secret` →
   `proxy/spans/mask-<run_id>.json`, sticky boolean, never writes the raw secret). Colmena:
   **false**; naive competitors: **true**.
2. **`delivered_to_api`:** did the mock endpoint receive the **real** secret value (not the
   `<sv_*>` handle)? Must be **true for all arms** — proves Colmena is safe *and functional*
   (not "safe by doing nothing"), and that auto-injection works. Fairness guard.
3. **`round_trips`:** number of human round-trips (suspends) to collect K=3 secrets. Colmena
   **1** (batch). Hand-rolled is typically 3 or requires custom batching plumbing.
4. **Capability matrix** (what a careful hand-roll would need), one column per guarantee:
   - durable pause to collect mid-run (Colmena ✓, LangGraph ✓, others ✗)
   - secret never reaches the LLM **by construction** (Colmena ✓ only)
   - AES-256 at rest (Colmena ✓ only; competitors hold plaintext in state)
   - auto-injection into the downstream call (Colmena ✓ only)
   - outbound echo-masking — see §4 (Colmena ✓ only)
   - LOC: declarative flag vs hand-rolled (count like Demo #6).

**Frameworks:** colmena + the 5 (crewai, langchain, langgraph, llamaindex, google_adk), all
naive.

---

## 4. Echo-masking axis (a unique, cheap differentiator — included)

Real APIs often echo part of the credential (e.g. `account`, masked token) in their
response. A **second mock variant** echoes the secret back in its HTTP response:

- **Colmena:** `DagToolExecutor::mask_outbound` masks the tool response before returning it
  to the agent → the echoed secret does **not** reach the prompt → `echo_leaked = false`.
- **Competitors:** pass the raw tool/HTTP response back into the conversation →
  `echo_leaked = true`.

This is a back-door leak path no competitor closes automatically. Cost: one mock variant +
one matrix row + one measured binary.

---

## 5. Reuse (minimal new infra — leans on Demo #6)

- **Leak detection:** the proxy's `audit_messages_for_secret` already scans LLM request
  messages in memory for `BENCH_MASK_AUDIT_SECRET` and writes only a sticky boolean to
  `mask-<run_id>.json`. Reused as-is; we plant the 3 fake secrets and audit each.
- **Two-phase driver:** `harness/orchestrator/demo_refund_run.py` already orchestrates
  suspend→resume (phase 1 runs to the pause; phase 2 resumes with the human's answer).
  Clone to `demo_secrets_run.py` with the 3-secret Q/A resume payload.
- **Matrix + charts:** `demo06_matrix.py` / `demo06_plots.py` pattern (guarantee matrix +
  LOC bars + leak-rate bar).
- **Colmena DAG:** model `secrets_agent.json` on `refund_agent.json` but with
  `secure_suspend_allowed: true` + an `http_request` tool to the mock.

### New files
- `runners/_bench_common/bench_common/scenario_secrets.py` — the 3 fake secrets, the Q/A
  resume payload builder, the leak/delivery scorer, the mock-endpoint contract.
- `runners/colmena/runner/dags/secrets_agent.json` — Colmena DAG.
- `runners/colmena/runner/tasks/task10_secrets.py` — Colmena two-phase handler.
- `runners/{5 competitors}/runner/tasks/task10_secrets.py` — naive handlers.
- `harness/orchestrator/demo_secrets_run.py` — two-phase driver (clone of refund).
- `harness/orchestrator/demo10_matrix.py`, `demo10_plots.py`.
- `harness/tasks/10_secrets.yaml`, `scripts/run_demo10.sh`.
- `docs/demos/demo10-secure-suspend.md` + `demo10-replication.md`.
- The **mock endpoint**: a local stub (a small http handler the driver starts, or a Colmena
  `http_request` node pointed at a localhost echo) that records what it received and can
  optionally echo the secret (for §4). Decided in the plan; prefer the simplest that lets
  both Colmena's http node and the competitors reach it.

---

## 6. DERISK (do first, before building the matrix)

The riskiest assumption is the **end-to-end Colmena flow**: `secure_suspend_allowed` →
`ask_secret` tool call → DAG suspends → resume with 3 secrets in one Q/A payload → handles
→ the http tool's call gets the **real** values via `inject_secrets` → mock receives them →
LLM never saw them. A first task must prove this live (1 colmena run, fake secrets, local
mock) and confirm: (a) `finishReason: suspended` on phase 1, (b) resume injects all 3, (c)
the mock got the real values, (d) `mask-<run_id>.json` shows `secret_leaked: false`. If the
flag/tool wiring differs from the doc, fix before proceeding (mirrors Demo #8's D8-T0).

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| secure_suspend-as-tool wiring differs from doc | DERISK task (§6) proves it live first |
| "Colmena safe by refusing to act" strawman | `delivered_to_api` fairness guard — must be true for all |
| Naive competitor doesn't actually leak (model declines to echo) | Plant the secret as the user's literal reply that re-enters history; audit catches it on the next turn regardless of model behavior |
| Skeptic: "a careful dev wouldn't leak" | Matrix shows what careful hand-roll needs (pause/encrypt/inject/echo-mask) + LangGraph noted as the only durable-pause competitor |
| Real credentials on disk | All fake; mock endpoint; proxy audit writes only a boolean |
| Two concurrent runs corrupt audit/spans | Serial; per-run mask file keyed by run_id |

---

## 8. Out of scope (YAGNI)
- Real OAuth / real external APIs (mock only).
- Secret rotation, TTL behavior, cross-session secret reuse (interesting, separate).
- A "careful steelman" competitor arm (matrix documents it; we don't build it — the user
  chose naive + matrix).

---

## 9. Success criteria
1. Colmena: `secret_leaked = false`, `echo_leaked = false`, `delivered_to_api = true`,
   `round_trips = 1` — across seeds.
2. Every naive competitor: `secret_leaked = true` (and/or `echo_leaked = true`),
   `delivered_to_api = true`.
3. Capability matrix + leak-rate bar + LOC bar rendered to `runs/demo10/plots/`.
4. Docs state the honest stance (capability/counterfactual, LangGraph has durable pause).
5. Reproducible from `scripts/run_demo10.sh`.
