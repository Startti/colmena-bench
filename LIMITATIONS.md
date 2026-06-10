# Limitations

> **Honesty section** — non-negotiable for credibility.
>
> A benchmark that claims wins everywhere reads as marketing. This document
> states explicitly where Colmena does NOT win, where this benchmark does
> NOT apply, and what assumptions could invalidate the results.

---

## 1. Tasks where Colmena does not clearly win

### Task 1 — Hello world (single tool call)
On a trivial single-tool task, all 6 frameworks produce ~the same token usage
and latency from the LLM API. Colmena's only meaningful advantage is cold-start
time and RAM footprint (relevant for serverless / Cloud Run scenarios, not for
a single dev running `agent.run("hi")`).

### Task 6 — RAG over PDF
LlamaIndex has 3+ years of mature primitives for retrieval, chunking, and
ranking. For pure RAG (retrieve-and-answer), LlamaIndex ties or beats Colmena.
**Colmena's recommended pattern is to use LlamaIndex as a retriever upstream
of Colmena's orchestration layer** — they are complementary, not competing.

## 2. Where this benchmark does NOT apply

- **Single-developer prototyping** — for one dev hacking on a single agent,
  ecosystem maturity (LangChain's 500+ integrations, community Stack Overflow
  answers) may outweigh Colmena's architectural advantages. The benchmark
  speaks to production deployments, not weekend prototypes.

- **Pure RAG applications** — see Task 6 above.

- **Highly LLM-bound workloads** — when 95%+ of latency is LLM API call time,
  framework differences become noise. The benchmark surfaces differences
  in framework-overhead-dominated scenarios.

- **Frameworks bypassing `base_url` override** — if a framework hardcodes
  its provider endpoint and bypasses standard SDK env vars, the LLM proxy
  cannot capture its calls. Such frameworks are flagged in the
  compatibility matrix.

## 3. Assumptions that could invalidate results

| Assumption | Failure mode |
|---|---|
| LLM provider pricing remains stable | If Gemini/Anthropic change pricing, USD figures stale. Mitigated by dated `pricing_table.json`. |
| Framework versions don't change | LangChain releases weekly. Pinned versions; results valid only for that snapshot. |
| Network conditions stable | Some latency variance is network-driven. N=30 + CI bootstrapping mitigates. |
| LLM determinism with temp=0 | Even at temp=0, providers may produce slight variation. Reported as variance. |
| Proxy doesn't bias TTFT | LiteLLM adds ~5-20ms. Reported as baseline offset, subtracted in analysis. |
| Tool implementations are equivalent | The same logical tool may be implemented slightly differently per framework. Adversarial review (week 12) mitigates. |

## 4. What this benchmark does NOT measure

- **Community size, documentation quality, Stack Overflow answer count.**
  LangChain wins these by 100×. Acknowledged.
- **Number of pre-built integrations.** LangChain has 500+; Colmena has 25
  production-curated. Different philosophies.
- **Long-term API stability.** Requires multi-year observation; out of scope.
- **Subjective DX ("which feels nicer").** LOC is a proxy but not perfect.
- **Cost of training/onboarding engineers.** Real but unmeasured.

## 5. Re-running this benchmark

Anyone can clone, install, and re-run. If your results differ:
1. Check that framework versions match (see lock files).
2. Check `manifest.json` for hardware comparability.
3. Open an issue with your `manifest.json` and `aggregated/` outputs.

We commit to re-running every 6 months to keep results current.
