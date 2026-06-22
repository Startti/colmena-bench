# Demo #10 — `secure_suspend`: Interactive Encrypted Secret Collection

**Hypothesis:** collecting K credentials mid-conversation is ONE declarative node in
Colmena (`secure_suspend`) — encrypted, only opaque `<sv_*>` handles reach the LLM,
auto-injected into the downstream call — so the secret NEVER touches a prompt. The
idiomatic competitor approach (ask for the secret in the conversation) leaves it in the
transcript → the LLM sees it → leak.

This is a **capability + counterfactual** demo (like masking / HITL in Demo #6), not a
metric sweep. The win is a clean binary: *did the secret reach the model?*

## Scenario — API onboarding ("connect your account")
The agent must connect the user's account by calling a **mock** authenticated endpoint. It
needs **3 secrets** that don't exist at deploy time — `api_key`, `api_secret`,
`webhook_signing_secret` — so it must ask the human mid-flow.

- **Colmena (hero):** an `llm_call` with a `secure_suspend` tool that collects all 3 in
  **one batch**; the DAG suspends, the human supplies them in **one resume round-trip**,
  AES-256-encrypted into `secure_value_mappings`; the agent only ever sees `<sv_*>`
  handles; a `secure: true` tool gets the **real** values auto-injected (`inject_secrets`)
  to POST to the endpoint; the tool's response is echo-masked before it re-enters the agent.
- **Competitors (naive idiomatic):** ask for the secrets in the chat → the user's reply
  enters the message history → the secret is in the prompt → leak.

Leak is measured by the LiteLLM proxy's in-memory audit (scans every LLM request for the
secret marker, records only a sticky boolean — never the raw secret). Secrets are **fake**;
the endpoint is a **local mock**; zero real credentials.

## Result — `leak_rate.png` (6 frameworks × 2 variants × 3 seeds = 36 cells, 0 errors)

| framework | secret_leaked (collect) | secret_leaked (echo) | delivered | round-trips |
|---|---|---|---|---|
| **colmena** | **0 / 3** | **0 / 3** | 3/3 | 1 |
| crewai | 3 / 3 | 3 / 3 | 3/3 | 1 |
| langchain | 3 / 3 | 3 / 3 | 3/3 | 1 |
| langgraph | 3 / 3 | 3 / 3 | 3/3 | 1 |
| llamaindex | 3 / 3 | 3 / 3 | 3/3 | 1 |
| google_adk | 3 / 3 | 3 / 3 | 3/3 | 1 |

**Colmena leaked in 0 of 6 runs; every competitor leaked in all 6.** And every arm has
`delivered_to_api = true` — Colmena is safe **and** functional (it really delivers the
secret to the endpoint, not "safe by refusing to act"). Colmena collected all 3 secrets in
a **single** round-trip.

![leak rate](../../runs/demo10/plots/leak_rate.png)

### Two variants, both clean for Colmena
- **collect** — the natural collection path. Colmena returns handles → no leak;
  competitors put the pasted secret in the transcript → leak.
- **echo** — the mock echoes the secret back in its HTTP response. Colmena's
  `DagToolExecutor` masks the tool response before it re-enters the agent → still no leak;
  competitors pass the raw response/transcript → leak. (Competitors already leak at
  collection, so echo just re-confirms it; the echo variant's real point is that Colmena
  closes even this back-door path.)

## Capability matrix — `capability_matrix.png`
What a careful hand-roll would need, by guarantee:

| guarantee | Colmena | LangGraph | others |
|---|:--:|:--:|:--:|
| Durable pause to collect mid-run | ✓ declarative | ✓ `interrupt()` | ✗ |
| Secret never reaches the LLM **by construction** | ✓ | ✗ | ✗ |
| AES-256 encryption at rest | ✓ | ✗ | ✗ |
| Auto-injection into the downstream call | ✓ | ✗ | ✗ |
| Outbound echo-masking | ✓ | ✗ | ✗ |
| Batch K secrets in 1 round-trip | ✓ | hand-rolled | hand-rolled |

## Honesty caveats
- **Capability/counterfactual demo, not a metric sweep.** Security is Colmena's proven
  suit; the result is a guarantee (no leak, by construction, from one declarative node).
- **LangGraph genuinely has durable HITL** (`interrupt()`) — stated in the matrix. The
  point is that even with it, keeping the secret out of state + encrypting + auto-injecting
  + echo-masking is all hand-rolled, and the *idiomatic* mid-conversation collection leaks
  (our `langgraph` naive arm leaked 6/6, same as the rest).
- **All secrets fake; endpoint mocked; the proxy audit writes only a boolean** (never the
  raw secret to disk).
- **`delivered_to_api` fairness guard** is true for all arms — competitors aren't penalized
  for "not working"; they work, they just expose the secret to the model on the way.

## Reproduce
`bash scripts/run_demo10.sh --frameworks "colmena crewai langchain langgraph llamaindex google_adk" --variants collect,echo --seeds 3`
See [demo10-replication.md](demo10-replication.md). Cheap (~36 small cells).
