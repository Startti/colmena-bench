# How to Sell Colmena (evidence-based)

The goal of colmena-bench is to sell Colmena **on differences that are real,
measured, and survive a skeptic.** This doc is the playbook: what to claim, with
what evidence, and — just as important — what NOT to claim.

---

## 1. The one-line pitch

> **Colmena keeps your LLM context lean by design.** Documents and large/binary
> tool outputs are managed by the engine — not pinned into history — so a
> multi-turn agent costs a fraction of the tokens, with no extra code. In our
> 10-turn benchmark across 6 frameworks, Colmena used **~6.6× fewer input tokens**
> and **~4.7× less money** than the median competitor, with identical answers.

That sentence is fully backed by [demos/demo05-context-tax.md](demos/demo05-context-tax.md).

---

## 2. Where Colmena genuinely wins (lead with these)

### Win #1 — Context efficiency (MEASURED, the hero) ✅
- **Claim:** built-in context scrubbing + ephemeral attachments keep token cost
  flat as a conversation grows; competitors pay for the whole history every turn.
- **Evidence:** Demo 05 — **65,680 vs 386k–452k** total input tokens over 10 turns
  (~6.6×); the gap *compounds* with turn count; answer quality preserved.
- **Why competitors can't easily match it:** none of the 5 scrub binary/oversize
  tool outputs by default; you'd hand-write history trimming + attachment caching
  + base64 elision. Colmena ships it.
- **How to demo:** run `scripts/run_demo05.sh`, show the cumulative-tokens table —
  Colmena flat, everyone else climbing.

### Win #2 — Security: encrypted secrets + outbound masking (NOVEL) — *to demo (#2)*
- **Claim:** credentials are injected as opaque handles; the plaintext never
  reaches the model, even inside tool results.
- **Evidence (to be measured):** binary pass/fail — inject a secret into a tool,
  prove the plaintext appears in zero LLM-visible messages. Code:
  `dag_tool_executor.rs` `inject_secrets`/`mask_outbound`, AES-256-GCM
  `secure_value_mappings`.
- **Competitor reality:** none has built-in encrypted-secret + outbound masking.

### Win #3 — Durable, cross-process HITL (suspend/resume) — *to demo (#3)*
- **Claim:** pause for human approval, survive process death, resume elsewhere;
  bubbles through nested orchestrators.
- **Evidence (to be measured):** "survives a process restart? y/n" + the LOC to
  add an approval gate. Code: `suspend`/`secure_suspend`, Postgres snapshot keyed
  by `agent_session_id`.
- **Honesty:** rough parity with LangGraph (checkpointers + interrupt). Clear win
  over CrewAI/LangChain/LlamaIndex (you'd build the state store yourself).

### Win #4 — Production agent as JSON, not glue code (node-vs-code) — *to demo (#4)*
- **Claim:** a *prod-hardened* agent (HITL + retries + critic loop + masking) is a
  declarative JSON DAG, not hundreds of lines of framework code.
- **Evidence (to be measured):** config lines + #files to stand up an
  approve/reject/revise flow with auto-recovery, vs the same in each competitor.
- **Honesty (critical):** this is about **production hardening**, NOT "it's a
  graph" (LangGraph/ADK are graphs too) and NOT trivial agents. See §4.

---

## 3. The recommended demo sequence for a prospect

1. **Demo 05 (context tax)** — the money shot; concrete $ and token numbers.
2. **Demo #2 (masking)** — the security checkbox; binary, unarguable.
3. **Demo #4 (prod agent in JSON)** — the "how little you maintain" story.
4. **Demo #3 (durable HITL)** — for buyers who care about long-running/approval
   workflows; pitch honestly vs LangGraph.

---

## 4. What NOT to claim (these backfire under scrutiny)

- **❌ "Runs more agents in parallel / higher throughput."** Colmena's engine is a
  *sequential* worklist; even `parallel:true` tasks await in a loop. Rust buys
  lower per-node overhead and RAM, **not** concurrency. You lose this comparison.
- **❌ "Fewer lines of code" for trivial/multi-turn-chat agents.** Measured: on a
  simple multi-turn chat, Colmena needs a per-turn `run_dag` driver and has the
  *highest* agent-construction LOC (62) because competitors ship a ready chat
  primitive. The LOC win is real only for **production** agents (Win #4) — make
  that scope explicit. Never cite Demo 05 LOC as a Colmena win.
- **❌ "Cheaper per token / same strategy is cheaper."** Token *price* is the same
  model through the same provider. Colmena wins on **how much context it sends**,
  not on unit price. (The old CSV naive-vs-expert result is a *strategy*
  difference any framework with a SQL tool ties — keep it as a secondary
  data-analytics note, not a headline.)
- **❌ "Hello-world is leaner."** Trivial agents are a wash across frameworks.

---

## 5. Why the numbers are trustworthy (say this proactively)

- **Provider-authoritative tokens** captured at a shared proxy — not framework
  self-report.
- **Identical conditions** — same model, same proxy, same inputs/scripts; pinned
  versions.
- **Idiomatic competitors** — their own default memory, no handicaps.
- **Adversarially reviewed** — an independent skeptic pass confirmed Demo 05 is
  fair (and the LOC caveat above came out of that review — we publish it rather
  than hide it).

The credibility *is* the product here: leading with an honest weakness (LOC on
simple agents, no parallelism) makes the strong claims (tokens, security) land.

---

## 6. Status of the evidence

| Pitch | Demo | Status |
|---|---|---|
| Context efficiency (Win #1) | Demo 05 | ✅ measured, 6 frameworks, live |
| Outbound masking (Win #2) | Demo #2 | ⏳ to build |
| Durable HITL (Win #3) | Demo #3 | ⏳ to build |
| Prod agent in JSON / node-vs-code (Win #4) | Demo #4 | ⏳ to build |
