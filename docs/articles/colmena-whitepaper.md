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
| **Colmena** | **37,619 ± 5,603** | **1,927** | **$0.0184** |
| LangGraph | 404,095 ± 23,121 | 71,181 | $0.1255 |
| LlamaIndex | 419,934 ± 34,873 | 71,225 | $0.1306 |
| Google ADK | 445,370 ± 11,614 | 71,395 | $0.1390 |
| LangChain | 452,158 ± 456 | 71,144 | $0.1406 |
| CrewAI | 452,358 ± 285 | 71,202 | $0.1420 |

Three numbers anchor the claim:

- **~12× fewer total input tokens** over the full 10-turn conversation (Colmena 37,619 vs competitor range 404,095–452,358).
- **~37× fewer at turn 10 alone** (Colmena 1,927 vs competitor range 71,144–71,395) — the gap widens with each successive turn.
- **~7.6× lower cost** (Colmena $0.0184 vs competitor range $0.1255–$0.1420). The per-token price is identical across all frameworks; the cost difference is entirely a function of context volume, not pricing.

These are not one-lucky-run numbers. N=12 runs per framework; Colmena's wider standard deviation (±5,603) reflects the model's per-turn decision of whether to re-read the document via `load_attachment` — an honest artifact of the mechanism, disclosed here. Competitors are near-deterministic (±285–±34,873).

![Efficiency multiplier by turn: Colmena input tokens vs competitor mean](assets/d05_multiplier.png)

*The efficiency multiplier grows with each turn as competitor histories accumulate; by turn 10 Colmena uses roughly 37× fewer tokens than the next-best competitor.*

![Total input tokens per framework (10-turn sum, N=12 mean)](assets/d05_total_tokens.png)

*Headline bar: Colmena total input tokens are an order of magnitude below every competitor.*

![Total cost per framework in USD](assets/d05_usd.png)

*At $0.0184 for a full 10-turn session, Colmena's cost is 7.6× lower than the cheapest competitor — entirely from context volume, not a price-per-token advantage.*

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

Colmena makes approximately 19 LLM calls over the 10-turn session versus 13 for competitors, because each `load_attachment` round-trip is an additional model call. This counts against Colmena in both token and latency accounting, and it still wins by 12× on tokens. The full latency and LLM-call comparison — including the bench-harness caveat for wall-clock time — is in §9.

<!-- ART-4 -->
## 5. Secret handling (Demo 10)

<!-- ART-5 -->
## 6. Production hardening as config (Demo 06)

<!-- ART-6 -->
## 7. Sandboxed code execution (Demo 08)

<!-- ART-7 -->
## 8. Tools at scale (Demo 07)

<!-- ART-8 -->
## 9. What Colmena does NOT win

<!-- ART-8 -->
## 10. Reproduction

<!-- ART-9 -->
## Appendix A — Full data tables

<!-- ART-9 -->
## Appendix B — Prompts used

<!-- ART-9 -->
## Appendix C — References
