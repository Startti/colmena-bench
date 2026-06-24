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


<!-- ART-3 -->
## 4. The context tax (Demo 05)

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
