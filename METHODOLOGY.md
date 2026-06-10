# Methodology

> **Status**: placeholder — to be expanded as the harness is built.
> Each section here will be filled with the exact code, configuration, and
> measurement strategy as the implementation progresses. The whitepaper
> derives directly from this document.

---

## 1. Framework versions

Pinned snapshot taken on **2026-06-09** (to be updated when locking):

| Framework | Version | Lock file |
|---|---|---|
| Colmena | 0.4.0 (commit TBD) | `runners/colmena/Cargo.lock` |
| CrewAI | TBD | `runners/crewai/uv.lock` |
| LangChain | TBD | `runners/langchain/uv.lock` |
| LangGraph | TBD | `runners/langgraph/uv.lock` |
| Google ADK | TBD | `runners/google_adk/uv.lock` |
| LlamaIndex | TBD | `runners/llamaindex/uv.lock` |

## 2. LLM models

Primary: `gemini-2.5-flash` (provider: Google).

Cross-validation (Tasks 4 and 5):
- `claude-haiku-4-...` (provider: Anthropic)
- `gpt-4o-mini` (provider: OpenAI)

All runs use `temperature=0.0`. Where the provider supports seeding, fixed seed = 42.

## 3. Hardware

- CPU: TBD (snapshot of `/proc/cpuinfo` per run goes in `manifest.json`)
- RAM: TBD
- OS: TBD
- Cloud: TBD (Task 7 uses a separate VM — to be specified)

## 4. How each metric is measured

(See [the design doc](../colmena/docs/superpowers/plans/2026-06-09-colmena-benchmark-design.md#estrategia-de-medición) for the full table.)

| Metric | Source of truth |
|---|---|
| Tokens input/output | LLM proxy (provider metadata) |
| Tokens cached | LLM proxy (per-provider field) |
| Total latency | Runner wall-clock |
| Framework overhead | total_latency − Σ proxy_span_latency |
| TTFT | LLM proxy (first SSE chunk timestamp) |
| Cost USD | Offline: tokens × `pricing_table.json` (dated snapshot) |
| RAM | Runner (psutil/procfs) |
| Cold-start | subprocess.spawn → "ready" marker |
| Tool calls | Proxy count cross-checked with runner |
| LOC | Script over `tasks/*.py` per runner |
| Success rate | Numeric exact match or LLM-as-judge per task |

## 5. Statistical methodology

- **N = 30** runs per (task, variant, framework) tuple unless noted.
- Reported statistics: **p50, p95, p99 with bootstrap 95% confidence intervals.**
- Overlapping CIs are reported as ties — no "winner" claim made.
- Outliers (>3σ) flagged but not removed; reported in appendix.

## 6. Adversarial validation

Pre-publication: 1 external expert per non-Colmena framework reviews the
runner implementation in their framework. Their PRs live in
[`adversarial_reviews/`](./adversarial_reviews/) with names and signatures
recorded for the whitepaper.

## 7. Reproducibility

Every run is uniquely identified by `run_id` (UUID). The combination of:
- Pinned framework versions (lock files)
- Pinned dataset (seed-generated, generator committed)
- Pinned proxy config (`proxy/litellm_config.yaml`)
- Pinned hardware (manifest)

…allows any third party to clone, run, and verify.
