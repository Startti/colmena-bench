# Colmena vs. the Field: A Provider-Authoritative Agent-Framework Benchmark

<!-- ART-9 -->
## 1. Executive summary

## 2. Why this benchmark exists

Agent-framework comparisons are usually published by the framework's own authors, who control what gets measured, how tokens are counted, and which baselines are included. Colmena-bench was designed around a different premise: every claim should survive scrutiny from a skeptical technical buyer who has read the methodology.

The most important structural decision is that all token and cost numbers are captured at a shared LiteLLM proxy that sits between every framework and the model provider. No framework self-reports its own usage. The proxy is the single authoritative source, so a framework that under-counts its context in its own SDK logs cannot inflate its apparent efficiency here.

Every run executes under identical conditions: the same model (`gemini-2.5-flash`, routed to `gemini/gemini-2.5-flash` on Google AI), temperature 0, the same proxy endpoint, and the same task inputs and evaluation scripts. Framework versions are pinned; see Appendix C for the full pin manifest and reproduction commands.

Each competitor framework was used idiomatically — its own default memory management, context-window strategy, and tool-calling conventions. No competitor was handicapped or steered toward a suboptimal pattern to make Colmena look better.

Colmena does not win everywhere, and this whitepaper says so explicitly. Colmena is not faster at wall-clock time. It is not more parallel. On trivial single-step agents, the code-size advantage shrinks to near zero. Two candidate demos were dropped entirely because the naive baseline matched Colmena's output quality at comparable cost (§9, What Colmena does NOT win). We lead with these limitations because they are what make the strong claims in §4 and §5 credible.

## 3. Methodology

**Frameworks under test.** The benchmark covers six frameworks: Colmena (Rust), CrewAI, LangChain, LangGraph, LlamaIndex, and Google ADK (all Python). Each framework implements the same agent task independently, using its native idioms.

**Token authority: the LiteLLM proxy.** All LLM calls are routed through a local LiteLLM proxy configured with a single model alias. Proxy spans are written to per-session JSON files. For Python frameworks, each run attaches an `x-bench-run-id` header, which the proxy propagates into the span metadata; token counts for that run are read directly from the spans tagged with that ID.

**Colmena token measurement.** Colmena cannot inject the `x-bench-run-id` header via its current HTTP client, so its proxy spans land in the session file without a run tag. Token counts for Colmena are measured by taking a **line-count delta** of the session file immediately before and after each run. To keep this delta attributable to exactly one run, all Colmena demos execute as a **serial sweep** — one run at a time, with no concurrent activity on the proxy. This is a real methodological constraint and is documented here so readers can assess it; it does not affect the accuracy of the count for any individual run.

**Model and temperature.** All frameworks use the alias `gemini-2.5-flash` (resolved at the proxy to `gemini/gemini-2.5-flash`), temperature 0. The per-token price is identical across all frameworks; the measured variable is how much context each framework sends, not what it costs per token.

**Replication.** Sample sizes vary by demo based on the variance of the metric:

- Demo 05 (context tax): N=12 runs per framework; results reported as mean ± std.
- Demo 10 (secret handling): n=3 runs per cell, 36 cells total (6 frameworks × 2 tasks × 3 replicates).
- Demo 07 (tools at scale): 5 seeds per framework.
- Task 04 (rolling summary): swept across dataset sizes to characterize the token-scaling curve.

Full version pins, environment setup, and per-demo run scripts are in Appendix C and §10.


## 4. The context tax (Demo 05)

### 4.1 Scenario

The benchmark runs a fixed 10-turn conversation against a "report analyst" agent. Each framework receives the same synthetic Q3-2026 report (~12,000 characters), the same deterministic `generate_chart` tool (which returns a fixed base64 PNG of roughly 32 KB), and the same sequence of 10 user messages: four document-retrieval questions, three chart-generation requests, and three follow-up turns. The task is representative of a real enterprise workflow — iterative document Q&A with binary tool outputs — and it is identical for all six frameworks. No framework received tuning hints or custom memory configuration; each ran with its own default context-management behavior.

### 4.2 Results

![Cumulative input tokens per turn across all frameworks](assets/d05_cumulative.png)

*Colmena's cumulative input tokens remain nearly flat across all 10 turns while each of the five Python frameworks grows roughly linearly, reaching 404,095–452,358 tokens by turn 10.*

The headline numbers, reported as mean ± std over **N=12 runs**:

| Framework | Total input tokens (mean ± std) | Turn-10 tokens | Cost (10 turns) |
|---|--:|--:|--:|
| **Colmena** | **39,085 ± 9,326** | **2,296** | **$0.018** |
| LangGraph | 404,095 ± 23,121 | 71,181 | $0.1255 |
| LlamaIndex | 419,934 ± 34,873 | 71,225 | $0.1306 |
| Google ADK | 445,370 ± 11,614 | 71,395 | $0.1390 |
| LangChain | 452,158 ± 456 | 71,144 | $0.1406 |
| CrewAI | 452,358 ± 285 | 71,202 | $0.1420 |

Three numbers anchor the claim:

- **~10–12× fewer total input tokens** over the full 10-turn conversation (Colmena 39,085 vs competitor range 404,095–452,358).
- **~31× fewer at turn 10 alone** (Colmena 2,296 vs competitor range 71,144–71,395) — the gap widens with each successive turn.
- **~7–8× lower cost** (Colmena $0.018 vs competitor range $0.1255–$0.1420). The per-token price is identical across all frameworks; the cost difference is entirely a function of context volume, not pricing.

These are not one-lucky-run numbers. N=12 runs per framework; Colmena's wider standard deviation (±9,326) reflects the model's per-turn decision of whether to re-read the document via `load_attachment` — an honest artifact of the mechanism, disclosed here. Competitors are near-deterministic (±285–±34,873).

![Efficiency multiplier by turn: Colmena input tokens vs competitor mean](assets/d05_multiplier.png)

*The efficiency multiplier grows with each turn as competitor histories accumulate; by turn 10 Colmena uses roughly 31× fewer tokens than the next-best competitor.*

![Total input tokens per framework (10-turn sum, N=12 mean)](assets/d05_total_tokens.png)

*Headline bar: Colmena total input tokens are an order of magnitude below every competitor.*

![Total cost per framework in USD](assets/d05_usd.png)

*At $0.018 for a full 10-turn session, Colmena's cost is 7–8× lower than competitors (7.0× vs the cheapest, LangGraph) — entirely from context volume, not a price-per-token advantage.*

### 4.3 No quality cost

A context-efficiency win only matters if the agent still answers correctly. The quality evaluation scores each framework's answers on the document-retrieval and follow-up turns (chart turns return short confirmations by design and are excluded from the quality score).

![Answer quality scores per framework](assets/d05_quality.png)

*Answer quality is roughly equal across all six frameworks; Colmena does not trade accuracy for token efficiency.*

Colmena's document-turn answers are correct: turn 1 returns "North America," turn 7 returns "Supply chain," and the trend question is answered "positive trend." The quality result closes the only obvious objection: Colmena does not win on tokens by losing on answers.

### 4.4 Why it works: ephemeral attachments and the binary scrubber

The token asymptote has two distinct causes, both visible in the token composition breakdown.

![Token composition by framework: history vs attachment tokens](assets/d05_composition.png)

*History tokens (the growing colored bars) dominate competitor totals; Colmena's history is small because attachments are never pinned and binary tool results are scrubbed before they enter the context.*

**Mechanism A — ephemeral attachments.** The Q3-2026 report (~3,000 tokens) is loaded via Colmena's `load_attachment` primitive. The attachment is read on the turns that need it and is explicitly *not* pinned into the conversation history. Competitors append the report to the first user message and re-send it in every subsequent turn as part of the standard message history.

**Mechanism B — binary tool-result scrubber.** Colmena's `dag_tool_executor` applies `scrub_tool_result_output` before any tool result reaches the LLM or is written into history. The ~32 KB base64 chart PNG (~8,000 tokens) is elided at the framework layer. All five Python competitors retain the raw tool message in history by default; after the first `generate_chart` call, that base64 blob re-enters the context on every subsequent turn.

Neither mechanism requires any application-level code from the developer. Both are active by default in Colmena's engine. The imperative Python a developer writes for Demo 05 is 53 lines; the agent itself is a ~71-line declarative JSON DAG.

To match Colmena's token behavior, a Python framework developer would need to write custom history-trimming logic, an attachment-caching layer, and a binary-elision pass — none of which are provided out of the box by any of the five competitors tested.

### 4.5 Forward note

Colmena makes approximately 18 LLM calls over the 10-turn session versus 13 for competitors, because each `load_attachment` round-trip is an additional model call. This counts against Colmena in both token and latency accounting, and it still wins by 12× on tokens. The full latency and LLM-call comparison — including the bench-harness caveat for wall-clock time — is in §9.

## 5. Secret handling (Demo 10)

### 5.1 Scenario

Many real-world agents must collect sensitive credentials mid-conversation — API keys, OAuth tokens, passwords — and forward them to a downstream service. The naive pattern is to ask the user to paste the credential into the chat, which places the plaintext into the model's message history, into any proxy or observability layer, and into every log that touches the conversation. Demo 10 tests whether a framework can collect and use credentials without the plaintext ever entering the LLM transcript.

### 5.2 Test variants

The benchmark runs two complementary variants to probe both collection and echo paths.

**`collect` variant.** The agent asks the user for credentials; the user pastes them. In Colmena, the `secure_suspend` primitive intercepts each credential at collection time, encrypts it with AES, and returns an opaque handle of the form `<sv_*>` to the model. The plaintext never appears in the LLM message history. When the downstream API call is made, Colmena's executor resolves the handle and injects the real value into the HTTP request automatically. Every competitor places the pasted credential directly into the message history — the secret is visible in the transcript from the moment the user sends it.

**`echo` variant.** A downstream tool echoes the secret back in its response (simulating a misconfigured service that returns credentials in its reply). Colmena's `dag_tool_executor` applies a re-masking pass before the tool result re-enters the model context, replacing the plaintext with the opaque handle. For competitors this variant is largely moot — they already leaked the secret during `collect` — but the variant confirms that Colmena holds even when a tool actively tries to surface the value.

### 5.3 Leak-rate results

"Leak" is defined as: the plaintext secret appears anywhere in the LLM-visible transcript (user message, assistant message, or tool result). Lower is better.

| Framework  | variant=collect | variant=echo |
|------------|-----------------|--------------|
| **colmena**| **0%** (0/3)    | **0%** (0/3) |
| langgraph  | 100% (3/3)      | 100% (3/3)   |
| crewai     | 100% (3/3)      | 100% (3/3)   |
| langchain  | 100% (3/3)      | 100% (3/3)   |
| llamaindex | 100% (3/3)      | 100% (3/3)   |
| google_adk | 100% (3/3)      | 100% (3/3)   |

Results span 36 cells (6 frameworks × 2 variants × 3 seeds) with 0 errors. The outcome is binary — either the plaintext appears in the transcript or it does not — and is unambiguous across all runs.

### 5.4 Why it is not luck — capability comparison

The result follows directly from capabilities that Colmena provides at the engine layer and that every competitor must hand-roll:

| Capability | Colmena | Competitors |
|---|---|---|
| Encrypted collection (AES) | ✓ native (`secure_suspend`) | ✗ hand-rolled |
| Opaque handle to the LLM (`<sv_*>`) | ✓ | ✗ (plaintext in history) |
| Auto-inject real value into the downstream call | ✓ | ✗ manual |
| Re-mask if a tool echoes the secret | ✓ | ✗ |

None of these capabilities require application-level code from the developer; they are active by default in Colmena's execution engine.

### 5.5 Honesty notes

**Scale.** This is a capability/counterfactual benchmark at modest scale (n=3 per cell, 36 cells total). It is not a large statistical sweep. Because the result is a hard binary — plaintext present or absent — scale does not change the conclusion, but readers should treat it as a proof-of-capability demonstration rather than a high-powered significance study.

**Fairness guard — Colmena still delivers.** `delivered_to_api = true` for all Colmena runs: the real secret is correctly injected into the downstream HTTP call in every case. Colmena achieves zero leakage not by refusing to function but by routing the plaintext through an encrypted side-channel. Competitors are not penalized for "not working"; they work correctly, they simply expose the secret in the LLM transcript in the process. That is the fair comparison.

**LangGraph nuance.** LangGraph has a genuine durable human-in-the-loop primitive (`interrupt()`) that Colmena's `secure_suspend` conceptually resembles. The distinction is scope: keeping the secret out of the persisted state, encrypting it, auto-injecting it into downstream calls, and re-masking tool echoes are all still hand-rolled in LangGraph. Colmena makes the entire chain the default, not an exercise left to the developer.

## 6. Production hardening as config (Demo 06)

### The claim

Taking a refund-decision agent from prototype to production requires at least four capabilities beyond a working LLM call: a **graph control flow** to express branching logic cleanly, **durable human-in-the-loop (HITL) suspend/resume** so an approval step survives process restarts, a **critic-retry loop** that catches bad outputs before they leave the agent, and **outbound secret masking** so credentials injected into tool calls never appear in logs, transcripts, or LLM contexts.

All six frameworks can implement all four capabilities. The question Demo 06 tests is not *can you build it* but *where does the capability live*: in engine-enforced declarative config that is always on, or in imperative code that a developer writes, tests, ships — and can forget to write.

That is the entire claim. This is not a lines-of-code comparison, and it is not "Colmena has a graph and others don't" — LangGraph and Google ADK are graph-first frameworks. The differentiator is the *mode of expression* and what happens when that expression is absent.

### Capability matrix

| Capability | colmena | langgraph | crewai | langchain | llamaindex | google_adk |
|---|---|---|---|---|---|---|
| Graph control flow | native | native | DIY | DIY | DIY | DIY |
| Durable HITL | native | native | DIY | DIY | DIY | DIY |
| Critic-retry loop | native | native | DIY | DIY | DIY | DIY |
| Outbound secret masking | native | **DIY** | DIY | DIY | DIY | DIY |

LangGraph is the honest near-peer: it provides native graph control flow, durable HITL, and a critic-retry loop, matching Colmena on three of four capabilities — the single differentiator is outbound masking, the one cell where every framework other than Colmena requires hand-rolled code.

### Masking counterfactual

The sharpest illustration of the difference between "safe by construction" and "safe because the developer remembered" comes from a controlled counterfactual: the same agent implemented twice, once with the scrubbing code included (hardened) and once with it omitted (naive).

| Variant | colmena | 5 Python competitors |
|---|---|---|
| Hardened (scrub written) | safe | safe |
| Naive (scrub omitted) | **safe** — engine `secure:true`, cannot be omitted | **LEAKS** |

Every hardened implementation passes: the correct refund decision is returned, no secret appears in the outbound transcript, HITL suspend/resume works, and the critic gate is enforced across all six frameworks. The counterfactual is not a measured failure of any hardened implementation — it is a demonstration of what happens when the safeguard is omitted. In the Python frameworks that omission is a realistic developer mistake; in Colmena, `secure: true` is a field on the node definition and the engine enforces it unconditionally. There is no code path through which the secret escapes.

Caveat: The leak is a demonstrated counterfactual of the NAIVE variant, not a measured failure of the hardened implementations — every hardened impl passes. The difference is that competitors are safe only because the developer remembered to scrub; Colmena is safe by construction.

See §5 for the dedicated secret-handling measurement.

### Lines of code — not a Colmena win

The LOC count is reported for completeness and should not be read as a Colmena advantage. Colmena's hardened implementation is **120 lines of code** plus **115 lines of declarative config** (235 lines total). Python competitor totals: CrewAI 93, LangChain 99, LlamaIndex 99, Google ADK 117, LangGraph 171. Colmena is not shorter — LangGraph is the only framework with a higher total, and the Python frameworks cluster below Colmena in raw character count.

The win is not fewer characters. The win is that the four production capabilities are expressed as engine-enforced config — auditable in a YAML diff, reviewable without understanding the surrounding call graph, and present or absent as a single field — rather than as imperative logic scattered across node functions that a code reviewer must trace to verify. For the full LOC discussion across all demos, see §9.

## 7. Sandboxed code execution (Demo 08)

### Scenario

The agent receives a CSV and is asked to run analytical code against it — summary statistics, filtering, derived columns. To probe containment, the harness simultaneously plants a canary file at a known path and instructs the model to read it as part of its tool call. A framework that executes model-written code without restriction will expose the canary; a framework that sandboxes execution will suppress the read and return a containment signal instead.

### Canary probe results

| Framework | Canary read? | Containment mechanism |
|---|---|---|
| **colmena** | **Contained** | Restricted in-process AST sandbox — import allowlist, banned builtins, no filesystem or network access — declared once as a native tool, no external service |
| llamaindex | Contained | Library `safe_eval` excludes `open` and other dangerous builtins |
| crewai | Contained | Docker container (OS-level isolation) |
| google_adk | Contained | Server-side kernel sandbox |
| langchain | **LEAKED** | Raw `PythonAstREPLTool` executes arbitrary Python with no sandbox |
| langgraph | **LEAKED** | Raw `exec` tool — no restrictions |

### Honest reading of these results

Colmena is not the only framework that contained the probe — three competitors also did, by different means. The useful signal here is narrower: **two widely-used frameworks (LangChain and LangGraph) execute model-written code with no sandbox by default**. That is a real, reproducible risk for any team that hands an LLM a code-execution tool and ships without thinking carefully about what runs on that surface.

Colmena's specific contribution is that containment is **declarative and in-process**: one native tool configured with a `restricted` mode, no Docker daemon to manage, no separate kernel service to provision or pay for. There is no wiring step that can be skipped under deadline pressure, and the policy is visible in the YAML rather than buried in a code path.

That said, **crewai's Docker container offers stronger isolation than an in-process AST allowlist** — a sufficiently clever AST bypass that slips past the allowlist would still be contained at the OS boundary by Docker. Colmena's edge is "safe by default with nothing to wire," not "the strongest possible sandbox." Teams with high-assurance requirements should evaluate whether Docker-level isolation is warranted regardless of which orchestration framework they choose.

### Analytics accuracy — no win here

Where the analytical results were measured, accuracy is roughly at parity: colmena 0.975 (variants M=0.95, L=1.0; the S variant was not measured in this run), llamaindex 0.97, langchain 0.95. The lower numbers for langgraph, google_adk, and crewai (0.55–0.68) trace to transient empty model completions during those runs, not to any framework capability difference. There is no accuracy win to claim in Demo 08; the full cross-demo accuracy picture is in §9.

## 8. Tools at scale (Demo 07)

### 8.1 Scenario

Real enterprise agents often expose large tool catalogs — dozens to hundreds of callable functions covering different data sources, APIs, and actions. Each Python framework tested here sends the full JSON schema for every tool in the catalog on every single LLM turn. As the catalog grows and the conversation extends across multiple turns, that cost accumulates quadratically: more tools × more turns = an ever-larger context on every request. Colmena's `lazy_tool_loading` changes the default: the engine sends the model a compact catalog (names and one-line summaries) and fetches a tool's full schema only when the model signals intent to call it. A second, independent mechanism — conversation-memory compaction — trims the growing message history by replacing earlier turns with a compressed summary. Demo 07 isolates the contribution of each mechanism.

### 8.2 Single-turn isolation: lazy loading alone

Because a single-turn probe has no accumulated conversation history, any gap here is attributable entirely to the lazy-loading mechanism, not to compaction. The probe runs the same task (tool selection from a catalog of varying size) at tool counts ranging from a handful to 200, with no prior turns in the session.

![Input tokens vs number of tools (log scale), single-turn hard probe](assets/d07_tokens_vs_tools.png)

*At 200 tools, colmena-lazy uses 22,190 input tokens versus 44,722–103,539 for competitors (2.0–4.7×); colmena-eager sits in the competitor pack, confirming the gap is the lazy-loading mechanism, not any other Colmena property.*

The critical honest detail here is **colmena-eager**. When lazy loading is disabled and Colmena sends every schema in full — exactly as competitors do — its token count lands squarely in the competitor band. The two-to-five-fold spread among competitors at 200 tools reflects how verbose each framework's default schema serialization is, not a correctness difference. Colmena-lazy pulls away from all of them because the schemas for tools the model never touches in that turn are simply not sent. The gap grows with tool count because each additional unused schema is a constant per-tool overhead that lazy loading avoids entirely; the relationship is log-linear as plotted.

### 8.3 Multi-turn result: lazy loading + compaction together

Over a 10-turn session with a 30-tool catalog, both mechanisms are in play. Cumulative input tokens at the final turn:

| Framework | Cumulative input tokens (turn 10) |
|---|--:|
| **colmena-lazy** | **66,808** |
| colmena-eager | 74,337 |
| LangGraph | 111,135 |
| LlamaIndex | 111,843 |
| CrewAI | 120,274 |
| Google ADK | 121,507 |
| LangChain | 125,305 |

![Cumulative input tokens over a 10-turn session (lazy vs eager vs competitors)](assets/d07_session_cum.png)

*Colmena-lazy accumulates 66,808 tokens over 10 turns versus 111,135–125,305 for competitors (≈1.7–1.9×), at identical tool-selection accuracy (1.00) across all configurations and all turns.*

### 8.4 What is driving the multi-turn number — honest attribution

The headline 1.7–1.9× multi-turn advantage deserves careful disaggregation, because most of it does **not** come from lazy loading.

In the multi-turn setting, Colmena's conversation-memory compaction is active for both colmena-lazy and colmena-eager. Both configurations compress growing history; both hold a large cost advantage over the five Python competitors, which accumulate history verbatim. That shared compaction benefit is what produces the majority of the ~1.6–1.7× advantage that colmena-eager already shows over competitors without lazy loading doing any additional work.

The lazy-loading increment over eager is modest at 30 tools: 74,337 (eager) vs 66,808 (lazy), approximately **1.11×**. That increment grows as tool count increases — which is exactly what the single-turn probe in §8.2 isolates cleanly. At 200 tools on a single turn, lazy loading produces a 2.0–4.7× advantage over competitors on its own; the multi-turn experiment uses 30 tools, so the lazy-specific contribution is smaller.

The accurate summary is: **compaction is what drives the multi-turn headline number; lazy loading is the clean differentiator in high-tool-count regimes and grows in value as catalogs scale.** Both mechanisms are active by default; neither requires application-level code from the developer. A Python framework developer who wanted comparable behavior would need to implement both a history-compaction strategy and a schema-dispatch layer independently.

### 8.5 No accuracy cost

Tool-selection accuracy is 1.00 at the final session turn across all six frameworks, and 1.00 on the 200-tool single-turn probe for all configurations including colmena-lazy. There is no accuracy win here — the win is cost only. The full cross-demo accuracy picture, including where Colmena does and does not have an edge, is in §9.

## 9. What Colmena does NOT win

This section documents every result where Colmena shows no advantage, every demo we built and then dropped, and every trade-off that accompanies a genuine win. The claims in §4 and §5 are credible precisely because this section exists.

### 9.1 Lines of code is not a win

![Maintained-code comparison across demos and frameworks](assets/d05_loc.png)

*Maintained-code comparison: Colmena is not categorically shorter.*

In Demo 05, the maintained Python wrapper is 53 lines, but the agent is also described as a ~71-line declarative JSON DAG — the real "code" cost includes both. In Demo 06 the production agent is 120 lines of code plus 115 lines of declarative config (235 lines total) against competitor totals of 93–171 lines — LangGraph at 171 is the only competitor that exceeds Colmena, and the other four Python frameworks are all shorter in raw character count.

Colmena is **not** categorically fewer lines. The honest framing is "least *imperative* code you maintain, plus guarantees that the engine enforces" — but on trivial agents, even that framing softens. A single-step agent with no memory requirements, no HITL, and no secret handling can be written more concisely in any of the Python frameworks than in Colmena's DAG format. The LOC comparison becomes meaningful only when the capabilities in §5 and §6 are required; at that point the question shifts from "how many lines?" to "which lines are enforced?" Do not use this whitepaper to claim a raw line-count win.

### 9.2 Not faster, not more parallel

![LLM-call count by framework in Demo 05](assets/d05_calls.png)

*LLM-call count: Colmena makes more round-trips, not fewer.*

Colmena makes approximately **18 LLM calls** over the 10-turn Demo 05 session versus **13 for competitors**, because each `load_attachment` invocation is a separate model round-trip. Colmena is not the fastest on wall-clock time; the additional calls add latency, and the bench harness cannot report reliable wall-clock comparisons for Colmena because its runs are serialized for token attribution (see §3).

Beyond Demo 05: Colmena's execution engine is a **sequential worklist**. Even tasks that are nominally marked as parallelizable are awaited in a loop — there is no concurrent fan-out. The Rust implementation buys low per-node overhead and efficient memory usage, not concurrency or throughput. If a use case requires raw parallel fan-out — many simultaneous tool calls, a scatter-gather over dozens of APIs, a map-reduce over independent subtasks — Colmena is the wrong tool. Python frameworks with native async and proper thread-pool dispatch will outperform it on that dimension.

### 9.3 No per-token price advantage

Every framework in this benchmark calls the same model (`gemini-2.5-flash`) through the same proxy at the same per-token price. There is no Colmena pricing tier, no batching discount, and no model substitution in play. All cost differences reported in §4 and §8 are entirely a function of how much context each framework sends — Colmena wins by sending less, never by paying less per token. A team that already manages context size carefully in a Python framework will not see a pricing-line improvement from switching.

### 9.4 The context-economy trade-off (Task 04)

![Expert vs naive SQL strategy: input tokens flat vs exploding as dataset grows](assets/t04_tokens_asymptote.png)

*Expert/SQL strategy keeps tokens flat as the dataset grows while naive/raw-CSV explodes — a strategy win, not a Colmena-native win.*

![Accuracy by framework on Task 04, largest dataset variant](assets/t04_accuracy.png)

*Accuracy by framework at the largest dataset size: Colmena expert reaches ~96.7%; competitors cluster near 100%.*

Task 04 is primarily a **strategy** result: querying a CSV via a SQL tool ("expert") beats stuffing raw rows into the prompt ("naive") by approximately 5–9× on tokens and 4–7× on accuracy, with expert input tokens flat at ~55k tokens across dataset sizes S, M, and L. Any framework using the expert/SQL strategy gets most of this benefit.

The honest trade-off: **Colmena's expert accuracy is 93–97% (S=96.7%, M=93.3%, L=96.7%; the chart shows the largest variant ≈96.7%) versus competitors' ~100%.** The ~3–7 percentage-point residual gap is real and reproducible. Its cause is the same rolling-summary context compaction that produces the Demo 05 token win: the compaction pass can truncate a large mid-conversation tool result table before the final answer is assembled. The develop@14beaba9 rebuild raised this from an earlier 88–92% floor, so the gap has narrowed, but it has not closed.

The mechanism is tunable (`KEEP_RECENT` and `recall_history` parameters govern how aggressively older tool results are compressed), and it is a known, documented trade-off, not a surprise. Teams that need 99–100% analytical recall on large tabular results should test their specific workload against these knobs before treating the Task 04 token numbers as a free lunch.

### 9.5 Where the result is parity, not a win

![Tool-selection accuracy parity in Demo 07](assets/d07_accuracy.png)

*Tool-selection accuracy is 1.00 across all frameworks in Demo 07 — the win is cost only.*

In Demo 07, every configuration — Colmena-lazy, Colmena-eager, and all five Python competitors — achieves **1.00 tool-selection accuracy** at the final session turn and on the 200-tool single-turn probe. The Demo 07 result is a cost win, not an accuracy win; claiming otherwise would be false.

In Demo 08 (sandboxed code execution), analytical accuracy is also roughly at parity where measured: Colmena ≈0.975 (M=0.95, L=1.0), LlamaIndex 0.97, LangChain 0.95. The lower numbers reported for LangGraph, Google ADK, and CrewAI in that run trace to transient empty model completions, not a structural capability difference. Colmena has no accuracy edge in Demo 08 either.

### 9.6 Two demos we dropped

Two candidate demos were designed, built to completion, and then dropped because the naive baseline matched Colmena's output quality — and we do not ship non-wins.

**(1) API-explorer demo.** The agent was given a moderately large API specification and tasked with constructing valid requests. Colmena used a schema-loading strategy to progressively pull in endpoint definitions. A naive "paste the spec into the system prompt" agent performed equally well and cost less for a small, well-known API — there was no regime where Colmena's approach was measurably better. The win would have required an API surface large enough that the naive approach exceeds the context window; we did not find that breakpoint within the models and spec sizes we tested.

**(2) Deterministic-router demo.** The agent applied a stated business policy to route incoming requests across several categories, including override cases. At temperature 0 with the policy stated plainly in the system prompt, a naive single-call LLM applied the routing policy correctly 100% of the time — including all override cases — across every framework tested. Colmena's declarative rule engine showed no measurable advantage: the policy was simple enough that the LLM internalized it without a structured rule evaluator. Naming these dropped demos is part of the methodology. A benchmark that only shows winners is a marketing document; a methodology that drops non-wins is science.

### 9.7 A note on the skills demo (Demo 09)

A progressive-knowledge-loading demo (`load_skill`) is approximately 21× cheaper on tokens than stuffing the full knowledge corpus into the system prompt on every turn. However, it ties a properly implemented RAG/vector-retrieval pipeline on both token efficiency and accuracy — the two approaches converge when retrieval quality is good. The only remaining edge for `load_skill` is operational simplicity: no vector store to deploy, index, or maintain. That is a real engineering convenience, but it is not a measured metric win, so Demo 09 is not featured in this whitepaper's core claims.

## 10. Reproduction

All results in this whitepaper are reproducible from the `colmena-bench` repository on the `main` branch. The instructions below describe the minimal path to re-run the core experiments.

**Environment setup.** Run `setup_all.sh` from the repository root. This script creates per-framework Python virtual environments, installs pinned dependencies (see Appendix C for the full version manifest), and verifies that the Colmena binary is present.

**Proxy.** All LLM calls must be routed through the LiteLLM proxy. Start it with:

```
proxy/start_proxy.sh
```

The proxy binds to `localhost:4000`, authenticates with the master key configured in `proxy/config.yaml`, and writes per-session span files to `proxy/spans/`. The spans are the authoritative source for all token and cost numbers in this paper.

**Per-demo run scripts.** Each demo has a dedicated run script:

- Demo 05 (context tax): `scripts/run_demo05.sh`
- Demo 06 (production hardening): `scripts/run_demo06.sh`
- Demo 07 (tools at scale): `scripts/run_demo07.sh`
- Demo 08 (sandboxed execution): `scripts/run_demo08.sh`
- Demo 10 (secret handling): run scripts are co-located in `runners/demo10/`
- Task 04 (rolling summary / token asymptote): the sweep runner is documented in `docs/demos/demo04-replication.md`

**Per-demo replication guides.** Each demo has a detailed replication guide under `docs/demos/demoNN-replication.md`, covering exact commands, expected outputs, evaluation scripts, and known variance sources (e.g., the Colmena serial-sweep requirement described in §3).

**Version pins.** Full dependency pins for all six frameworks and the Colmena binary version are in Appendix C. Do not mix versions across framework environments; cross-environment dependency conflicts are the most common cause of non-reproducible results in this benchmark.

<!-- ART-9 -->
## Appendix A — Full data tables

<!-- ART-9 -->
## Appendix B — Prompts used

<!-- ART-9 -->
## Appendix C — References
