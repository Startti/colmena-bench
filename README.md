# colmena-bench

Comparative benchmark of [Colmena](https://github.com/Startti/colmena) against the 5 leading AI agent orchestration libraries:

- [CrewAI](https://github.com/crewAIInc/crewAI)
- [LangChain](https://github.com/langchain-ai/langchain)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [Google ADK](https://github.com/google/adk-python)
- [LlamaIndex](https://github.com/run-llama/llama_index)

## Goals

Demonstrate **quantitatively and reproducibly** how Colmena compares on:

- Latency (p50/p95/p99)
- Token consumption (input/output/cached)
- Number of tool calls
- Cost in USD per task
- Throughput under concurrency
- Robustness under tool failure
- Handling of large data (CSV up to 500K rows)
- Multimodal handling (image + PDF + audio without context poisoning)

## Status

🚧 **Work in progress** — see [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) for the ordered task list and timeline.

## Documents

- [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) — ordered tasks, dependencies, owners, effort
- [METHODOLOGY.md](./METHODOLOGY.md) — how we measure (canonical reference)
- [LIMITATIONS.md](./LIMITATIONS.md) — where this benchmark does NOT apply
- Design doc (in colmena repo): `docs/superpowers/plans/2026-06-09-colmena-benchmark-design.md`

## Quick links once running

```bash
./scripts/setup_all.sh                    # Install all venvs + Rust toolchain + proxy
./scripts/verify_baseline.sh              # Sanity check (5 min)
./scripts/run_task.sh 04 --variant M --N 30 --framework all
./scripts/run_all.sh --N 30               # Full suite (overnight)
```

## Secrets & environment

API keys and local config live in a `.env` file at the repo root. **Never
commit `.env`** — it is in [`.gitignore`](./.gitignore).

1. Copy the template: `cp .env.example .env`
2. Fill in `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
3. Adjust `LITELLM_PROXY_*` only if you need a non-default port
4. CI reads the same variables from GitHub repo secrets — see `ci/`

The LiteLLM proxy (T03) is the single chokepoint for LLM credentials at
benchmark time: runners receive only `LITELLM_PROXY_BASE_URL` and a dummy key,
the real provider keys never reach framework code.

## License

MIT — see [LICENSE](./LICENSE).
