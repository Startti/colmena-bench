# colmena-bench

A **provider-authoritative** benchmark comparing [Colmena](https://github.com/Startti/colmena) (a Rust agent engine) against the five leading Python agent frameworks under identical model, temperature, and task conditions:

- [CrewAI](https://github.com/crewAIInc/crewAI) · [LangChain](https://github.com/langchain-ai/langchain) · [LangGraph](https://github.com/langchain-ai/langgraph) · [LlamaIndex](https://github.com/run-llama/llama_index) · [Google ADK](https://github.com/google/adk-python)

Every LLM call from every framework routes through one shared LiteLLM proxy, and all token/cost figures are read **at the proxy** rather than from framework self-reports — so no framework can under- or over-count its own usage. Model: `gemini-2.5-flash` at temperature 0.

## The paper

The full write-up, with methodology, figures, and per-experiment analysis:

- **[paper/main.pdf](paper/main.pdf)** — the primary deliverable ([LaTeX source](paper/main.tex))
- [docs/site/colmena-business.html](docs/site/colmena-business.html) — business-facing summary
- [METHODOLOGY.md](METHODOLOGY.md) · [LIMITATIONS.md](LIMITATIONS.md) · [docs/TECHNICAL.md](docs/TECHNICAL.md)

## Experiments

Each experiment has a one-command run script and a write-up + replication guide under [`docs/demos/`](docs/demos/). Results land in `runs/<demo>/summary.{json,csv}` and `runs/<demo>/plots/`.

| Experiment | What it measures | Run | Write-up |
|---|---|---|---|
| Calibration | Single-tool-call latency/cost baseline, per framework | `scripts/run_task.sh 01` | [runs/task01/report/report.md](runs/task01/report/report.md) |
| Context Tax | Multi-turn input-token growth (ephemeral attachments + scrubber) | `scripts/run_demo05.sh` | [demo05-context-tax.md](docs/demos/demo05-context-tax.md) |
| Production Hardening | Graph + durable HITL + critic + masking as config vs code | `scripts/run_demo06.sh` | [demo06-refund-agent.md](docs/demos/demo06-refund-agent.md) |
| Tools at Scale | Token cost of large tool catalogs (lazy loading + compaction) | `scripts/run_demo07.sh` | [demo07-many-tools.md](docs/demos/demo07-many-tools.md) |
| Sandboxed Code Execution | Does model-written code escape its sandbox? | `scripts/run_demo08.sh` | [demo08-codeexec.md](docs/demos/demo08-codeexec.md) |
| Progressive Knowledge Loading | On-demand skill loading vs prompt-stuffing / RAG | `scripts/run_demo09.sh` | [demo09-skills.md](docs/demos/demo09-skills.md) |
| Credential Isolation | Does a plaintext secret reach the LLM transcript? | `scripts/run_demo10.sh` | [demo10-secure-suspend.md](docs/demos/demo10-secure-suspend.md) |
| Query-Strategy Trade-off | SQL-tool vs raw-CSV strategy on tokens & accuracy | `scripts/run_task4_all.sh` | [task04-csv.md](docs/demos/task04-csv.md) |
| Concurrency Ceiling | Throughput/RAM under concurrent load (mock LLM, 0 tokens) | `scripts/run_demo13.sh` | [demo13-concurrency.md](docs/demos/demo13-concurrency.md) |

Each run script owns the proxy lifecycle. A `<demo>-replication.md` beside each write-up documents the exact mechanism, scoring, and expected output.

## Setup

Building the Colmena runner requires a local checkout of
[Startti/colmena](https://github.com/Startti/colmena) (Rust + maturin).
Clone it, then point `setup_all.sh` at it:

```bash
git clone https://github.com/Startti/colmena.git ../colmena   # or any path

cp .env.example .env          # then fill in the keys below
COLMENA_REPO=../colmena scripts/setup_all.sh   # builds the bench venv, the 5 framework venvs, the Colmena engine, the proxy
scripts/verify_baseline.sh    # quick end-to-end sanity check
```

Then run any experiment, e.g.:

```bash
bash scripts/run_demo10.sh    # Credential Isolation across all 6 frameworks
```

Subsets are supported where relevant, e.g. `bash scripts/run_demo10.sh --frameworks "colmena langgraph" --seeds 3`.

## Secrets & environment

API keys and local config live in a `.env` at the repo root. **Never commit `.env`** — it is in [`.gitignore`](.gitignore).

- `GEMINI_API_KEY` — the model provider for all runs
- `LITELLM_MASTER_KEY` — the proxy's auth key
- `COLMENA_DATABASE_URL`, `SECURE_VALUES_KEY` — required by the Colmena engine (Postgres URL; ≥32-char key)

The LiteLLM proxy is the single chokepoint for provider credentials at benchmark time: runners receive only `LITELLM_PROXY_BASE_URL` and a dummy key, so the real provider key never reaches framework code.

## Provenance

Framework versions are pinned in the setup scripts and documented in the whitepaper's appendices. Colmena is built from a pinned `develop` commit; the exact tag/commit per experiment is recorded in the whitepaper. Because the Python binding declares the same version string across builds, provenance is tracked by git tag/commit, not by the pip version.

## License

MIT — see [LICENSE](LICENSE).
