# Implementation Plan — colmena-bench

> **Design doc**: [`colmena/docs/superpowers/plans/2026-06-09-colmena-benchmark-design.md`](../colmena/docs/superpowers/plans/2026-06-09-colmena-benchmark-design.md)
>
> **Timeline**: 12 weeks (with 2 engineers) — see capacity note below
> **Team**: **2 engineers required for the 12-week timeline** (1 Rust+Python senior + 1 Python+DevOps). A single engineer would extend this to ~20-22 weeks.
> **Budget**: ~$12,500 external (API costs, adversarial reviewers, design)
>
> **Capacity sanity check**: total estimated effort is ~120 person-days. With 2 engineers @ 5 days/week × 12 weeks = 120 days available — fits with no slack. A single engineer cannot deliver in 12 weeks; scope must be reduced or timeline extended.

---

## How to read this document

Tasks are ordered by **dependency**, not by who works on them. Multiple tasks within the same phase can run in parallel.

Each task has:
- **ID**: T01, T02, … (referenced by other tasks for dependencies)
- **Phase**: which of the 5 phases it belongs to
- **Deps**: prerequisite task IDs
- **Effort**: rough estimate in person-days
- **Deliverable**: concrete artifact verifiable by another person
- **Owner**: TBD (fill in as work is assigned)

Phase boundaries represent **logical milestones**, not strict gates. Some Phase 2 work can start before Phase 1 fully closes if dependencies allow.

---

## Summary of phases

| Phase | Weeks | Tasks | Goal | Critical output |
|---|---|---|---|---|
| **0 — Foundation** | 1-2 | T01-T10 (10 tasks) | Repo scaffolding, proxy, schemas, datasets | Proxy captures tokens; orchestrator skeleton parses YAMLs |
| **1 — Skeleton runners** | 3-5 | T11-T19 (9 tasks) | All 6 framework runners implement Task 1; **T11 is a gate** | First comparative report |
| **2 — Core differentiators** | 6-8 | T20-T26.5 (8 tasks) | Tasks 2, 3, **4 (killer demo)** complete in all 6 | **Killer demo charts + optional teaser blog post** |
| **3 — Remaining tasks** | 9-11 | T27-T33 (7 tasks) | Tasks 5, 6, 7, 8, 9, 10 complete | Full benchmark dataset |
| **4 — Validation & publication** | 12+ | T34-T40 + T34.5 (8 tasks) | Adversarial review, whitepaper, pitch deck | Public release |

> **Reviewer sourcing (T34.5) must start in week 9-10** — 3 weeks lead time. It runs in parallel with Phase 3.

---

## Phase 0 — Foundation (weeks 1-2)

Goal: by end of phase 0, `./scripts/verify_baseline.sh` runs successfully end-to-end with a single trivial task on Colmena + 1 other framework, with the LLM proxy capturing tokens correctly.

### T01 — Initialize git repo and basic structure
- **Phase**: 0
- **Deps**: none
- **Effort**: 0.5 day
- **Deliverable**:
  - `git init` in `/Users/danielgarcia/startti/colmena-bench/`
  - First commit with README, LICENSE, .gitignore, this plan, METHODOLOGY/LIMITATIONS stubs
  - Public GitHub repo `Startti/colmena-bench` created (empty push)
- **Owner**: TBD

### T02 — Pin framework versions (snapshot 2026-06-09 or update date)
- **Phase**: 0
- **Deps**: T01
- **Effort**: 1 day
- **Deliverable**:
  - `runners/{crewai,langchain,langgraph,google_adk,llamaindex}/pyproject.toml` with explicit version pins
  - Lock files generated (`uv pip compile` or `poetry lock`)
  - `runners/colmena/Cargo.toml` pointing at specific Colmena commit
  - Versions documented in METHODOLOGY.md §1
  - **`.env.example`** at repo root listing required keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DATABASE_URL` optional)
  - Secret management documented in README (use `.env`, never commit)
- **Owner**: TBD

### T03 — Setup LiteLLM proxy locally
- **Phase**: 0
- **Deps**: T02
- **Effort**: 2 days
- **Deliverable**:
  - `proxy/litellm_config.yaml` with routes for Google (gemini-2.5-flash), Anthropic, OpenAI
  - `proxy/start_proxy.sh` script
  - JSONL log capture (`proxy/spans/run-*.jsonl`) verified manually with a curl test
  - Smoke test: call `gemini-2.5-flash` via proxy, verify `usage.input_tokens` captured correctly
- **Owner**: TBD

### T04 — Spike: base_url override compatibility per framework
- **Phase**: 0
- **Deps**: T02, T03
- **Effort**: 3 days
- **Deliverable**:
  - `docs/base_url_compatibility.md` matrix: for each of 6 frameworks, document
    how to redirect LLM calls to the proxy (env var, SDK config, monkey-patch)
  - A working "hello LLM" call routed through proxy in each framework
  - Identify problematic frameworks early — escalation list
- **Owner**: TBD

### T05 — Define JSON schemas
- **Phase**: 0
- **Deps**: T01
- **Effort**: 1.5 days
- **Deliverable**:
  - `harness/schemas/task.schema.json` — schema for YAML task definitions
  - `harness/schemas/run_output.schema.json` — schema for runner output JSON
  - `harness/schemas/aggregated.schema.json` — schema for aggregated stats
  - `harness/schemas/proxy_span.schema.json` — schema for proxy log entries
  - Validation tests in `harness/tests/test_schemas.py`
- **Owner**: TBD

### T06 — Dataset generator: orders_synthetic
- **Phase**: 0
- **Deps**: T01
- **Effort**: 2 days
- **Deliverable**:
  - `data/orders_synthetic/generator.py` (deterministic, seed-based)
  - `data/orders_synthetic/schema.json`
  - Generate `seeds/{S,M,L}.csv` (XL postponed to phase 2)
  - `data/orders_synthetic/README.md` documenting columns + distributions
- **Owner**: TBD

### T07 — Ground truth for orders_synthetic 20 questions
- **Phase**: 0
- **Deps**: T06
- **Effort**: 2 days
- **Deliverable**:
  - `data/orders_synthetic/questions_20.json` — 20 questions (5 trivial, 8 medium, 7 advanced)
  - `data/orders_synthetic/ground_truth.json` — canonical answers per question per dataset size
  - `data/orders_synthetic/compute_ground_truth.py` — SQL/pandas script that regenerates ground truth from seeds
- **Owner**: TBD

### T08 — Orchestrator skeleton + runner contract
- **Phase**: 0
- **Deps**: T05
- **Effort**: 2 days
- **Deliverable**:
  - `harness/runner_contract.md` — CLI interface specification (final)
  - `harness/orchestrator/run.py` skeleton (loads task YAML, invokes runner subprocess, collects output)
  - `harness/orchestrator/aggregate.py` skeleton (combines N runs into stats)
  - `harness/orchestrator/report.py` skeleton (markdown + PNG charts)
  - Unit tests for each
- **Owner**: TBD

### T09 — Task 1 (hello world) definition
- **Phase**: 0
- **Deps**: T05
- **Effort**: 0.5 day
- **Deliverable**:
  - `harness/tasks/01_hello_world.yaml`
  - Documented: prompt, expected tool, ground truth pattern, metrics
- **Owner**: TBD

### T10 — Pricing table snapshot
- **Phase**: 0
- **Deps**: T01
- **Effort**: 0.5 day
- **Deliverable**:
  - `harness/pricing_table.json` — current USD/token for all model/provider combos
  - Dated snapshot (2026-06-09 or current)
  - Verification script: `harness/tests/test_pricing.py` confirming format
- **Owner**: TBD

> **T11 moved to Phase 1** — it requires at least 2 runners to exist (Colmena + one Python), and those don't exist until T12 and T13 complete. See T11 in Phase 1 below.

**Phase 0 checkpoint**: LiteLLM proxy captures tokens correctly when called directly (verified via `curl`). Datasets generated and schemas validated. Orchestrator skeleton parses task YAMLs. Pricing table snapshotted. **The first end-to-end test (`verify_baseline.sh`, T11) is gated by Phase 1's first two runners.**

---

## Phase 1 — Skeleton runners (weeks 3-5)

Goal: all 6 framework runners implement Task 1 conforming to `runner_contract.md`. First comparative report generated.

> **Gate rule**: T11 (`verify_baseline.sh`) must pass after T12 + T13 land, before continuing with T14-T17. This catches harness bugs early — if tokens don't match between the proxy and the runners for 2 frameworks, they won't match for 6 either.

### T12 — Colmena runner: Task 1
- **Phase**: 1
- **Deps**: T04, T08, T09
- **Effort**: 2 days
- **Deliverable**:
  - `runners/colmena/runner.rs` (or invocation of Colmena CLI from a thin Rust wrapper)
  - `runners/colmena/tasks/01_hello_world.json` (DAG)
  - Runs Task 1, emits conformant JSON output
- **Owner**: TBD

### T13 — CrewAI runner: Task 1
- **Phase**: 1
- **Deps**: T04, T08, T09
- **Effort**: 2 days
- **Deliverable**:
  - `runners/crewai/runner.py` cumple runner_contract
  - `runners/crewai/tasks/task01.py`
  - Venv aislado funcionando con framework version pin
- **Owner**: TBD

### T11 — `verify_baseline.sh` smoke test (GATE)
- **Phase**: 1 (moved from Phase 0)
- **Deps**: T03, T08, T09, T12, T13
- **Effort**: 1 day
- **Deliverable**:
  - `scripts/verify_baseline.sh` runs Task 1 with N=3 against Colmena + CrewAI (or whichever 2 runners landed first)
  - Validates that proxy-captured tokens match runner-reported counts (within ±2%)
  - Validates `run_id` correlation between runner output JSON and proxy spans JSONL
  - Prints clear pass/fail and a one-page report to stdout
  - Documented in README
- **Owner**: TBD
- **🚦 Gate**: if this fails, **do NOT proceed with T14-T17 until root-caused**. A harness bug that affects 2 frameworks will affect all 6.

### T14 — LangChain runner: Task 1
- **Phase**: 1
- **Deps**: T04, T08, T09, **T11 must have passed**
- **Effort**: 2 days
- **Deliverable**: análogo a T13
- **Owner**: TBD

### T15 — LangGraph runner: Task 1
- **Phase**: 1
- **Deps**: T04, T08, T09
- **Effort**: 2 days
- **Deliverable**: análogo a T13
- **Owner**: TBD

### T16 — LlamaIndex runner: Task 1
- **Phase**: 1
- **Deps**: T04, T08, T09
- **Effort**: 2 days
- **Deliverable**: análogo a T13
- **Owner**: TBD

### T17 — Google ADK runner: Task 1
- **Phase**: 1
- **Deps**: T04, T08, T09
- **Effort**: 2 days
- **Deliverable**: análogo a T13
- **Owner**: TBD

### T18 — Orchestrator: full Task 1 run + aggregator + reporter
- **Phase**: 1
- **Deps**: T10 (pricing table for USD), T12-T17
- **Effort**: 3 days
- **Deliverable**:
  - `scripts/run_task.sh 01 --variant default --N 30 --framework all`
  - Outputs `results/<date>-v0.1/aggregated/01/stats.json`
  - Outputs `results/<date>-v0.1/report/report.md` with first comparative table
  - First chart (latency p50/p95 by framework) saved as PNG
- **Owner**: TBD

### T19 — Setup automation + CI
- **Phase**: 1
- **Deps**: T12-T17
- **Effort**: 2.5 days
- **Deliverable**:
  - `scripts/setup_all.sh` — installs all 6 venvs + Rust + proxy in fresh machine
  - Tested in clean macOS + Linux environments
  - Documented in README
  - **`ci/github_actions.yml`** — runs `verify_baseline.sh` on PR, runs Task 1 N=3 on `main` push as smoke test
  - **`ci/nightly.yml`** — full Task 1 + Task 2 N=10 nightly (optional, post-Phase 2)
- **Owner**: TBD

**Phase 1 checkpoint**: First comparative report for Task 1 published in `results/`. All 6 frameworks measurable. Baseline of "hello world" overhead documented.

---

## Phase 2 — Core differentiators (weeks 6-8)

Goal: Tasks 2, 3, and 4 (the killer demo) complete in all 6 frameworks. **Killer demo charts ready for use in pitch deck**.

### T20 — Tool catalog 50: dataset
- **Phase**: 2
- **Deps**: T19
- **Effort**: 1.5 days
- **Deliverable**:
  - `data/tool_catalog_50/tools.json` — 50 tool definitions (20 HTTP, 10 SQL, 10 math, 10 string ops)
  - `data/tool_catalog_50/reference_impls/` — mock implementations callable by each framework
- **Owner**: TBD

### T21 — Task 2 (tool catalog 50) definition + all runners
- **Phase**: 2
- **Deps**: T20, T19
- **Effort**: 5 days (across 6 frameworks)
- **Deliverable**:
  - `harness/tasks/02_tool_catalog.yaml`
  - Implementation in `runners/*/tasks/task02.*` for all 6
  - Comparative report generated
- **Owner**: TBD

### T22 — Task 3 (multi-step 5 tools) definition + all runners
- **Phase**: 2
- **Deps**: T19
- **Effort**: 8 days (5 deterministic mock tools × 6 frameworks + chain logic + verification)
- **Deliverable**:
  - `harness/tasks/03_multistep.yaml`
  - Tools: search_flights, get_weather, search_hotels, calculator, summarize (mocked deterministically)
  - Implementation in all 6 runners
  - Comparative report
- **Owner**: TBD

### T23 — Task 4 (CSV killer demo) — variant S (500 rows)
- **Phase**: 2
- **Deps**: T07, T19
- **Effort**: 10 days (naive AND expert implementations per framework = 12 effective implementations)
- **Deliverable**:
  - `harness/tasks/04_csv_analytical.yaml` with variants S/M/L/XL declared
  - Implementation in all 6 runners for variant S
  - Both **naive** (default tutorial path) AND **expert** (best practice) implementations per framework
  - Comparative report
- **Owner**: TBD

### T24 — Task 4 — variants M and L
- **Phase**: 2
- **Deps**: T23
- **Effort**: 2 days
- **Deliverable**:
  - Run all 6 runners against variants M (5K) and L (50K)
  - **Expected**: naive implementations break at L → document the failure mode
  - Comparative report extended
- **Owner**: TBD

### T25 — Task 4 — variant XL (500K rows, stretch)
- **Phase**: 2
- **Deps**: T24
- **Effort**: 2 days
- **Deliverable**:
  - Generate XL dataset
  - Run Colmena + 1-2 frameworks that survive (those with pandas/SQL approach)
  - Document which frameworks cannot reach XL even with expert implementation
- **Owner**: TBD

### T26 — Killer demo charts
- **Phase**: 2
- **Deps**: T23, T24, T25
- **Effort**: 2 days
- **Deliverable**:
  - **Chart 1**: the asymptote — tokens vs rows (log scale)
  - **Chart 2**: USD cost for 20 questions vs dataset size
  - **Chart 3**: Success rate vs dataset size
  - **Chart 4**: LOC for setup + implementation
  - All charts in `results/<date>-v0.2/report/charts/` as PNG + SVG + raw CSV
  - **These 4 charts are extractable for pitch deck immediately**
- **Owner**: TBD

### T26.5 — Interim teaser blog post (optional but recommended)
- **Phase**: 2 → 3 (publishable at end of Phase 2)
- **Deps**: T26
- **Effort**: 3 days
- **Deliverable**:
  - 2,000-word blog post focused exclusively on Task 4 (killer demo)
  - Published on Startti blog / Medium / dev.to
  - Includes the 4 killer demo charts + reproducibility note ("full whitepaper coming, repo at `...`")
  - **Purpose**: capture early mindshare + invite community feedback **before** the full whitepaper locks in. Hostile feedback now → stronger whitepaper later.
- **Owner**: TBD
- **Risk**: if reaction is "your LangChain implementation is naive", that's a free pre-emptive adversarial review. Embrace it.

**Phase 2 checkpoint**: Killer demo material ready. Internal pitch deck can be assembled from charts at T26 even before remaining tasks complete.

---

## Phase 3 — Remaining tasks (weeks 9-11)

### T27 — Task 5 (multi-turn 15 turnos)
- **Phase**: 3
- **Deps**: T19
- **Effort**: 6 days
- **Deliverable**:
  - `harness/tasks/05_multiturn.yaml`
  - Simulated 15-turn customer support conversation script
  - All 6 runners implement, including memory persistence
  - Charts: tokens turno-N, latencia turno-N, % cached, USD acumulado
- **Owner**: TBD

### T28 — RAG corpus + Task 6 (honest comparison)
- **Phase**: 3
- **Deps**: T19
- **Effort**: 9 days (LlamaIndex RAG is native; CrewAI + Google ADK + Colmena require more setup)
- **Deliverable**:
  - `data/pdf_corpus/` with 1 PDF (200pg arxiv paper or 10-K)
  - 30 questions + gold answers (human-written)
  - All 6 runners implement RAG (using their native primitives)
  - Honest comparison: report includes case where LlamaIndex ties/beats Colmena
- **Owner**: TBD

### T29 — Task 7 (100 agents concurrentes) — load testing harness
- **Phase**: 3
- **Deps**: T22 (uses Task 3 as base workload)
- **Effort**: 5 days
- **Deliverable**:
  - `harness/concurrency/` — Locust or k6 driver
  - Each runner exposes a long-running mode (instead of one-shot subprocess)
  - Throughput, RAM, p99 measured under load
  - Comparative chart: queries/sec per framework on identical hardware
- **Owner**: TBD

### T30 — Task 8 (chaos / tool failure recovery)
- **Phase**: 3
- **Deps**: T20
- **Effort**: 4 days
- **Deliverable**:
  - `data/tool_catalog_50/reference_impls/chaos_wrapper.py` with deterministic failure injection
  - All 6 runners use the wrapper for Task 8
  - Comparative: success rate, retries, tokens "wasted" in retries
- **Owner**: TBD

### T31 — Task 9 (HITL suspend/resume)
- **Phase**: 3
- **Deps**: T19
- **Effort**: 6 days (includes shared storage setup)
- **Deliverable**:
  - **Shared SQLite database** at `harness/state.db` for cross-process suspend state (runners can use it OR their own backend — both reported)
  - Migration script + schema documented in `harness/storage/README.md`
  - 2-phase driver: phase A (start, suspend, persist) + phase B (resume with answer); driver kills the runner process between phases to test true cross-process recovery
  - All 6 runners attempted; document which require manual hackery (LOC + effort)
  - **Expected outcome**: Colmena native, LangGraph close (checkpointers), CrewAI + LangChain + LlamaIndex + ADK require custom code
- **Owner**: TBD

### T32 — Multimodal corpus + Task 10
- **Phase**: 3
- **Deps**: T19
- **Effort**: 4 days
- **Deliverable**:
  - `data/multimodal/` — 1 product image, 1 spec PDF, target TTS audio
  - Gold answer for the audio summary content
  - All 6 runners implement
  - Comparative chart: tokens in history after multimodal flow (binary scrubber demonstration)
- **Owner**: TBD

### T33 — Cross-validation with secondary LLMs (Tasks 4 and 5)
- **Phase**: 3
- **Deps**: T26, T27
- **Effort**: 3 days
- **Deliverable**:
  - Re-run Task 4 and Task 5 with `claude-haiku` and `gpt-4o-mini`
  - Confirm or refute the gemini-2.5-flash results
  - Report appendix: "results robust across 3 LLMs"
- **Owner**: TBD

**Phase 3 checkpoint**: Full benchmark dataset complete. All 10 tasks measured in all 6 frameworks (with honest "not supported" where applicable).

---

## Phase 4 — Validation & publication (weeks 12+)

### T34 — Adversarial review coordination
- **Phase**: 4
- **Deps**: T34.5 (reviewers sourced), Tasks 1-10 complete
- **Effort**: 2 days coord + 2-3 weeks waiting for reviewers
- **Deliverable**:
  - Each contracted reviewer (1 per non-Colmena framework, 5 total) receives a **collaborative scope**:
    > "We've benchmarked your framework against Colmena. Here is our implementation in `runners/<your_framework>/`. We are asking you to improve it to **your best implementation following the official best practices of [framework]**. We will re-run with your improvements and report the new numbers — whoever wins. Your name and credentials will appear in the whitepaper acknowledgments **if you consent after seeing final results**. Compensation: $1,000 fixed, regardless of outcome."
  - **Consent form**: signed before review starts; reviewer can opt out of being named even after seeing results (compensation still paid)
  - **NDA**: light — covers unreleased Colmena code only; review work itself is public
  - Reviewer PRs land in `adversarial_reviews/<framework>/` for full transparency
  - Budget: ~$1,000 per reviewer × 5 = $5,000
- **Owner**: TBD

### T34.5 — Source adversarial reviewers
- **Phase**: 4 (must start in week 9-10 — 3 weeks lead time)
- **Deps**: none (can start in parallel with Phase 3)
- **Effort**: 5 days coord + 2-3 weeks of outreach
- **Deliverable**:
  - Shortlist of 3 candidate reviewers per framework (15 total) — sources: official Discord, framework maintainer lists, conference speakers, top GitHub contributors
  - Outreach emails sent, terms negotiated
  - 1 confirmed reviewer per framework (5 total)
  - Signed consent + NDA on file
- **Owner**: TBD
- **🚦 Risk note**: if no reviewer can be found for a framework, document this and proceed without — but it weakens that framework's section in the whitepaper. Worst case: re-do internal review with 2 different engineers and flag transparently.

### T35 — Incorporate adversarial review PRs
- **Phase**: 4
- **Deps**: T34
- **Effort**: 5 days
- **Deliverable**:
  - All accepted PRs merged into `runners/<framework>/`
  - Re-run affected tasks with improved implementations
  - Updated comparative reports
  - Reviewer names and signatures recorded in METHODOLOGY.md
- **Owner**: TBD

### T36 — Final aggregation + report generation
- **Phase**: 4
- **Deps**: T35
- **Effort**: 3 days
- **Deliverable**:
  - `results/<date>-v1.0/` final immutable results
  - Master report.md with all 10 tasks + cross-validation
  - All charts finalized (PNG + SVG)
  - Raw data CSV exported
- **Owner**: TBD

### T37 — Whitepaper draft
- **Phase**: 4
- **Deps**: T36
- **Effort**: 7 days
- **Deliverable**:
  - 60-80 page PDF following structure: Exec summary, Methodology, 10 benchmarks, Killer demo, Limitations, Architectural deep-dive, Reproducibility
  - Includes all charts from T36
  - Reviewed internally by Colmena team before publication
- **Owner**: TBD

### T38 — Pitch deck slides
- **Phase**: 4
- **Deps**: T36 (can start in parallel with T37)
- **Effort**: 3 days + design contractor budget ~$2000
- **Deliverable**:
  - 15-20 slide pitch deck (PPTX or Keynote)
  - 3 hero charts on cover: asymptote, throughput, USD/1M queries
  - Internal use for investor and client conversations
- **Owner**: TBD

### T39 — Publication checklist
- **Phase**: 4
- **Deps**: T37, T38
- **Effort**: 1 day
- **Deliverable**:
  - Repo made fully public
  - README finalized
  - Whitepaper published (URL: TBD — blog / arxiv / company page)
  - Hacker News + Twitter / Reddit r/MachineLearning post drafts
  - Commitment to re-run every 6 months posted
- **Owner**: TBD

### T40 — Docker images for reproducibility (post-v1)
- **Phase**: 4 (optional follow-up)
- **Deps**: T39
- **Effort**: 3 days
- **Deliverable**:
  - `docker/Dockerfile.*` per framework
  - `docker-compose.yml` orchestrating proxy + runners
  - Anyone can `docker compose up` and reproduce
- **Owner**: TBD

---

## Dependency graph (text version)

```
Phase 0:
  T01 ──► T02 ──► T03 ──► T04 ───┐
   │       │      │              │
   ├──► T05 ──► T08 ──► T09 ─────┤
   │       │                     │
   ├──► T06 ──► T07              │
   │                             │
   └──► T10                      │
                                 │
Phase 1:                         ▼
  (T04 + T08 + T09) ──► T12-T17 ──► T18 + T19

Phase 2:
  T19 ──► T20 ──► T21
   │      │
   ├──► T22
   │
   └──► T07 + T19 ──► T23 ──► T24 ──► T25 ──► T26 (killer demo charts ready)

Phase 3:
  T19 ──► T27, T28, T29, T30, T31, T32
  T26 + T27 ──► T33

Phase 4:
  (T27..T33 complete) ──► T34 ──► T35 ──► T36 ──► T37 + T38 ──► T39
                                                                   │
                                                                   └──► T40 (optional)
```

---

## Quick reference: critical path

The **critical path to the killer demo** (earliest delivery of usable pitch material):

```
T01 → T02 → T03 → T04 → T08 → T12-T17 (parallel) → T18 → T19 → T22 + T23 → T24 → T26
                                                                                  │
                                                                          KILLER DEMO READY
```

Approximate timeline: **6-8 weeks** to T26 if parallelized.

The **critical path to full publication**:

```
… → T26 → T27..T32 (parallel) → T34 → T35 → T36 → T37 → T39
                                                          │
                                                  PUBLIC RELEASE
```

Approximate timeline: **12-14 weeks** total.

---

## Risk register (active)

| Risk | Phase | Mitigation owner |
|---|---|---|
| Framework hardcodes provider URL (bypasses proxy) | 0 (T04) | TBD |
| Token capture inconsistency across providers | 0 (T03) | TBD |
| Naive implementation accusations | 4 (T34/T35) | TBD |
| API budget overrun | 2-3 | TBD |
| Frameworks publish breaking changes mid-bench | All | Pin in T02; document |

---

## Definition of Done — overall project

The benchmark is "done" when:

- [ ] All 10 tasks have results in all 6 frameworks (or documented "not supported")
- [ ] Adversarial review complete with at least 3 external reviewers signed off
- [ ] Whitepaper published (PDF + HTML)
- [ ] Pitch deck delivered to Colmena team
- [ ] Repo public with `make bench` reproducibility verified by at least one external party
- [ ] LIMITATIONS.md reviewed and reflects honest assessment
- [ ] Commitment posted to re-run every 6 months
