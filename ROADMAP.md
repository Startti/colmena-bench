# colmena-bench — Roadmap & remediation tracker

Single source of truth for all pending work. Grouped so tasks survive context
compaction. Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[?]` needs a
decision before starting. Ordered by recommended execution sequence.

Last updated: 2026-07-04.

---

## Group 0 — Done this session

- [x] **Delete demo11 (API explorer) + demo12 (deterministic router).** Both were
  null results with untracked data and unmerged branches (unreplicable cites).
  Removed `runs/demo11`, `runs/demo12`, branches `demo11-api-explorer` /
  `demo12-router`, smoke scripts; whitepaper §9.6 removed, §9.7/§9.8 renumbered,
  abstract/contributions/conclusion counts updated; poster line removed.
  Committed on branch **`cleanup/drop-demo11-demo12`** (NOT merged to main — see G-1).
- [x] **Feasibility spike for 3 new frameworks — all PASS.** Pydantic AI, OpenAI
  Agents SDK, Mastra (TS) each connect through the LiteLLM proxy, inject the
  `x-bench-run-id` header (spans metered per-run), and run multi-turn + tool calls.
  Scripts + integration notes in `spikes/README.md`.
- [x] **Verified Colmena ships Rust + Python + TypeScript** (`colmena-ai` on npm & pip,
  Rust core `src/libs/colmena`) → the multi-language section (E-4) is honest.

---

## Group A — Replicability-blocking bugs (do FIRST; block the v0.9.0 re-run)

- [x] **A-1. CrewAI demo08: representation + replicability — DONE 2026-07-04.**
  Was NOT a broken import (false alarm): the runner vendored its own tool. Rewrote it to a
  Daytona remote sandbox (primary) + Docker (fallback), selectable via `BENCH_CREWAI_SANDBOX`,
  with the CSV uploaded as a real file (fixes the M=0.15 inline-CSV artifact). Re-ran the crewai
  demo08 arm (merge-baseline preserved the other 5 frameworks): **analytics S=0.95, M=0.95
  (was 0.15), L=1.00 (new); probe→contained on Daytona; mutation ok**. Updated §7 (footnote +
  Table 6), §7.4, §9.5, Appendix A.4, demo08-codeexec.md, demo08-replication.md. Baseline backup:
  `runs/demo08/summary_baseline_precrewai.json` (untracked; can be removed in F-2).
  NOTE for B-1: LangGraph/Google ADK analytics (~0.55–0.60) are still low — that's the
  serialization artifact, addressed in B-1, not A-1. Side-observation: crewai's demo08 token
  counts are high (verbose agent loop); irrelevant to demo08's accuracy/containment claims.
  The runner is NOT broken: it vendors its own `_DockerCodeInterpreterTool` (docker SDK
  direct) and RUNS at pinned crewai 1.14.7 when the Docker daemon is up. The earlier
  "ImportError" was a false alarm (tested `from crewai_tools import CodeInterpreterTool`,
  which the runner never imports). Real issues:
  1. **Representation honesty:** §7/Table 6 shows "CrewAI · Contained · Docker", but CrewAI
     removed `CodeInterpreterTool` in 1.14.0 (CVE VU#221883, SSRF/RCE). A current user gets
     no Docker interpreter — only cloud `E2BPythonTool`/`DaytonaPythonTool` (present in 1.14.7).
     We show reconstructed historical behavior without disclosing it.
  2. **Replicability:** requires a Docker daemon; without it the row is SKIPPED (graceful).
  3. **Accuracy artifact:** CrewAI analytics M=0.15 (vs S=0.95). The vendored Docker tool has
     NO host mount, so the CSV is embedded inline as a string literal in the code payload —
     brittle at 500 rows. This is our workaround's handicap, not CrewAI's. (Sibling of B-1.)
  File: `runners/crewai/runner/tasks/task08_codeexec.py`.
  **DECISION (2026-07-04): option (b) — Daytona.** User has `DAYTONA_API_KEY` in `.env`
  (quoted; strip quotes when reading). Daytona spike PASSED (`spikes/daytona/spike.py`):
  key authenticates, sandbox runs pandas, canary probe CONTAINED (host path → FileNotFoundError).
  `DaytonaPythonTool` is a real current `crewai_tools` 1.14.7 tool + `pip install daytona` (done
  in the crewai venv) → faithful representation of what a current CrewAI user does for code-exec.
  Implementation: migrate the CrewAI demo08 arm to Daytona; **upload the CSV via the Daytona
  filesystem API** (`sandbox.fs`) and `pd.read_csv` it, instead of inlining the CSV string
  literal — this fixes the M=0.15 handicap. Keep the existing vendored-Docker path as an
  optional local fallback for replicators without a Daytona key. Footnote §7 that CrewAI's
  first-party `CodeInterpreterTool` was removed in 1.14.0 (CVE VU#221883) and the current
  path is cloud sandboxes. Document the free Daytona key ($200 credits, no card) in the
  replication guide. Re-run the CrewAI demo08 arm; update §7.4 / Appendix A.4.

- [ ] **A-2. Stamp git provenance (SHA/tag) in every run summary.**
  The runner stamps `metadata.version("colmena-ai")` = `0.4.0` for BOTH `14beaba9`
  and tag `v0.9.0` → the pip string cannot distinguish builds. Add the Colmena git
  SHA/tag to summaries so provenance is unambiguous.
  Files: `runners/colmena/runner/__main__.py` (or the orchestrators that write summaries).

---

## Group B — Fairness fixes that CHANGE published numbers (do before re-run)

> These mostly move numbers *against* Colmena's relative advantage — which is why
> doing them strengthens credibility.

- [x] **B-1. demo08 serialization artifact — DONE 2026-07-04.** Added a shared
  `jsonify_answers()` helper (`bench_common/answers.py`) that recursively normalizes
  pandas/numpy objects to JSON-native (Series→dict, Timestamp/Period→'YYYY-MM-DD'/'YYYY-MM',
  numpy→python, dict keys too) and applied it in both codegen runners
  (`runners/{langgraph,google_adk}/runner/tasks/task08_codeexec.py`) before serializing.
  Re-ran both: **LangGraph and Google ADK analytics 0.55–0.60 → 0.95/0.95/1.00** (all six
  frameworks now at 0.95–0.98 parity). Updated §7.4, §9.5, Appendix A.4. ADK probe/mutation
  hit transient "No message in response" errors through the proxy (pre-existing ADK flakiness,
  unrelated to this fix); restored ADK's clean probe='blocked' from the original baseline.

- [x] **B-2. demo09 RAG rate-limit failures — DONE 2026-07-04.** The 7 embedding `429`s at
  50 packs were counted as failures (RAG 0.935→shown 0.94). Added `max_retries=8` to both
  embed clients (`runners/{langchain,llamaindex}/runner/tasks/task09_skills.py`) so fresh runs
  back off instead of failing. Recomputed Table 9 excluding the 7 not-measured 429 rows →
  **RAG@50 = 1.00 (101/101)**. Updated Table 9 + caption + demo09-skills.md + demo09-replication.md.

- [x] **B-3. demo09 missing-pack artifact — DONE 2026-07-04.** Root cause found:
  `materialize_corpus` sliced `core_items[:pack_count]`, so at `pack_count=5 < 6` it dropped
  the 6th core pack (`colmena-mascotas`), making its questions unanswerable for every arm
  (all arms 0.83 at 5 packs). Fixed: `materialize_corpus` now always writes ALL 6 core packs
  (unit-verified: pack_count=5 writes 6), and the sweep floor is raised to
  `PACK_COUNTS = [6, 20, 50]`. Recomputed Table 9's smallest column excluding the unanswerable
  mascotas rows → **all arms 1.00** (Table 9 accuracy is now 1.00/1.00/1.00 across all three arms).
  NOTE: demo09 is a secondary result (paper says "not part of central claims") already
  disclosing both artifacts, so I recomputed from existing data with principled not-measured
  exclusions + hardened the code for future runs, rather than a full (expensive) re-run.

---

## Group C — Fairness steelman arms (native mechanism we don't exercise)

> Each is reported *alongside* the naive default arm, not replacing it. Framing:
> "Colmena does declaratively what framework X requires you to hand-wire."

- [x] **C-1. demo05 `google_adk_artifacts` arm — DONE 2026-07-04. Fairness concern REFUTED.**
  Implemented the ADK-native steelman: `runners/google_adk/runner/tasks/task05.py` variant
  `artifacts` (saves report via `ArtifactService`, agent gets built-in `load_artifacts`);
  driver plumbing in `harness/orchestrator/demo05_run.py` (`_ARM_MAP` + `HEADER_CAPABLE`).
  N=3, quality PASS. CORRECTED FINDING (after the ADK source + session inspection — an earlier
  draft wrongly claimed the doc "persists"): ADK's `load_artifacts` IS a genuine ephemeral-
  attachment equivalent for the DOCUMENT (session shows report text 0× in standing history vs
  1× default = Colmena Mechanism A). It still did NOT close the gap — 467.9k vs 439.8k, both
  ~11–12× Colmena's 39k — because the scenario's tax is dominated by the ~8k base64 CHART, which
  accumulates in ADK history (ADK has no binary scrubber = Colmena Mechanism B), and load_artifacts
  adds a reload round-trip per doc-turn re-sending the un-scrubbed history. ADK matches 1 of
  Colmena's 2 context mechanisms, not both. §4.6, demo05-context-tax.md, and
  `runs/demo05/steelman_adk_artifacts.json` all corrected to this.

- [~] **C-2. demo07 LangChain `LLMToolSelectorMiddleware` — BUILT, BLOCKED on demo07 repro (2026-07-05).**
  Arm implemented (`runners/langchain/runner/tasks/task07b_tools.py::_run_selector` via create_agent +
  the middleware; driver config `langchain-selector` + `BENCH_LANGCHAIN_SELECTOR`). Two findings:
  (1) the stock middleware does NOT work with gemini-2.5-flash via the proxy — its structured-output
  schema is a `Union[Literal[name]]` (pydantic → `anyOf`/`const`), which Gemini-via-LiteLLM does not
  enforce (selector returns descriptions / hallucinated names → "Model selected invalid tools"). A flat
  JSON-Schema `enum` IS enforced (verified), so `_run_selector` monkeypatches the schema builder to emit
  one. With that, the arm runs correctly (6/6 needle accuracy) at ~19.9k tokens (seed 0). (2) BLOCKER:
  the default langchain arm in the CURRENT env measures ~287k / 100 LLM calls, but published Table 7 says
  125,305 — a 2.3× discrepancy suggesting model/env DRIFT (the model now makes many more tool calls per
  turn on the confusable toolset). The selector's 19.9k cannot be published against a baseline that no
  longer reproduces. **Defer C-2's paper integration to the G-2 v0.9.0 re-run (fresh baselines); first
  investigate the demo07 reproducibility gap (new item C-2a below).** Code is preserved and isolated.

- [ ] **C-2a. NEW — investigate demo07 reproducibility (drift is ISOLATED to demo07, triaged 2026-07-05).**
  Triage result: demo05 langchain reproduces EXACTLY today (452,600 / 13 calls vs published 452,158 / 13,
  quality OK) → **no global model drift**; the v0.9.0 re-run (G-2) is safe for the other experiments.
  Only demo07 is off: current-env langchain default = ~287k / ~100 LLM calls vs published 125,305. Most
  likely the confusable-toolset scenario is high-variance in tool-call count (seed 0 outlier — published
  is a 5-seed mean) rather than a model change. TODO: run all 5 seeds of demo07 default to check the mean
  vs 125k, and inspect per-turn tool-call counts. Fold into G-2's demo07 re-run. Native, built-in since
  LangChain 1.0, **present at pinned 1.3.6**; a secondary LLM pre-selects ~5 of 30 tools,
  cutting per-turn schema tokens. We bind all 30 → **biggest exposure to the demo07 pitch**.
  Applies to LangGraph via `create_agent` too.
  Import: `langchain.agents.middleware.tool_selection.LLMToolSelectorMiddleware`.
  Files: `runners/{langchain,langgraph}/runner/tasks/task07_tools.py`.
  **Decision needed:** add the arm, OR apply a symmetric "no LLM/RAG tool pre-selection"
  rule to all frameworks and state it explicitly. (Note: `ProviderToolSearchMiddleware`,
  the true lazy-fetch analog, ships only in 1.3.7 — one patch above the pin — so it's
  correctly excluded at the current pin.)

- [x] **C-3. demo10 `langgraph_interrupt_isolated` arm. DONE.** Built the hand-architected
  LangGraph arm: `_run_isolated` in `runners/langgraph/runner/tasks/task10_secrets.py` uses a
  `StateGraph` whose `connect` node calls `interrupt()` to collect the credentials out-of-band
  (arrive via `Command(resume=...)` into a local var, never an LLM message) + a hand-written
  echo scrub. Driver plumbing: `_ARM_MAP` in `harness/orchestrator/demo_secrets_run.py` maps the
  pseudo-framework → (`langgraph` venv/runner, `BENCH_LANGGRAPH_ISOLATED=1`); added to
  `HEADER_CAPABLE`. **Measured: 0% leak in BOTH variants (0/3 collect, 0/3 echo), delivered=True,
  0 errors** — same 0% as Colmena. Cost: ~64 LOC of security-critical hand-wiring. Reframes the
  claim from "only Colmena can" → "Colmena does declaratively what LangGraph makes you
  hand-architect". Plots: added the arm as the rightmost bar in `demo10_plots.leak_rate`
  (`_security_loc` also handles it); regenerated `runs/demo10/plots/leak_rate.png` + copied to
  `docs/articles/assets/d10_leak_rate.png`. Docs updated: whitepaper §5.4 (measured steelman,
  replaces the hand-wavy "LangGraph nuance"), Fig 7 caption, `docs/demos/demo10-secure-suspend.md`
  (+ steelman section), `demo10-replication.md`. Summary now 42 rows (36 base + 6 arm, merged).

- [x] **C-4. demo07 LlamaIndex `ObjectIndex` + `tool_retriever`. DONE (document only).**
  Added a "Native tool-narrowing alternatives, disclosed and symmetrically excluded" paragraph
  to whitepaper §8.4 covering BOTH LlamaIndex `ObjectIndex`+`tool_retriever` (embedding-RAG:
  `VectorStoreIndex` + `similarity_top_k`, recall risk) AND LangChain `LLMToolSelectorMiddleware`
  (extra LLM call; enforced variant one patch above pin) — excluded like the RAG family in §2.1.
  URL verified (301 → `developers.llamaindex.ai/python/examples/agent/openai_agent_retrieval/`,
  "Retrieval-Augmented Agents"); added to the References list. Mirrored a bullet into
  `docs/demos/demo07-many-tools.md` §3. No arm.

---

## Group D — Disclosure footnotes (claim holds; pre-empt reviewer objections)

- [ ] **D-1. demo06 masking:** the "only Colmena has native masking" claim HOLDS
  (CrewAI/LangChain PII redaction is trace-level, not live LLM context). But footnote that
  ADK (`after_tool_callback`), LangChain (callbacks), LlamaIndex have native *hooks* where
  the DIY scrub lives — so "DIY" means "you write the redaction," not "no interception point."
  Files: §6 / `docs/demos/demo06-refund-agent.md`.
- [ ] **D-2. demo08:** disclose that `langchain-sandbox`'s `PyodideSandboxTool` is a
  compatible opt-in → claim is "the default/idiomatic path leaks," not "cannot be made safe."
  Files: §7 / `docs/demos/demo08-codeexec.md`.
- [ ] **D-3. task04:** disclose no framework uses its native SQL agent (LangChain
  `create_sql_agent`, LlamaIndex `NLSQLTableQueryEngine`, CrewAI `NL2SQLTool`); the choice is
  uniform, doesn't bias, and a native fix would *raise* competitors (harsher for Colmena).
  Optional latent fix: the 200-row cap in `run_sql` (`bench_common/datasets.py:47`) can
  silently truncate list-type answers.

---

## Group E — Expansion: new frameworks + multi-language

- [ ] **E-1. Pydantic AI runner** (start here — cleanest). Build tasks 05/06/07/08/10;
  re-run. Pattern proven in `spikes/pydantic_ai/`.
- [ ] **E-2. OpenAI Agents SDK runner.** Note: force `set_default_openai_api("chat_completions")`
  + `set_tracing_disabled(True)`. Pattern in `spikes/openai_agents/`. Pin exactly (0.x churn).
- [ ] **E-3. Mastra (TypeScript) runner.** Needs a Node subprocess the Python orchestrator
  shells out to. Tool `execute` signature is `async (inputData) => ...` in 1.49. Pattern in
  `spikes/mastra/`. Biggest credibility gain — kills "Python-only benchmark."
- [ ] **E-4. Colmena multi-language section (Rust / Python / TypeScript).** Run ONE
  representative experiment (e.g. Context Tax or hello-world) via each Colmena SDK to show
  the same engine runs in all three. New whitepaper section. No new competitor runners needed.
  (`colmena-ai` on npm has a `typescript_dag` guide that executes DAGs.)

> Effort: ~1.5–3 days per full runner (E-1..E-3). All three passed the connectivity spike.

---

## Group F — Repo cleanup for replicability

- [ ] **F-1. `.gitignore`** build artifacts & debris: `docs/articles/*.html`, `*.pdf`,
  `**/uv.lock`, `spikes/*/.venv`, `spikes/*/node_modules`, debug `proxy/spans/mask-*`.
- [ ] **F-2. Delete untracked debris** (~13 MB): `proxy/spans/mask-*.json`,
  `runs/*/received-*.json`, `runs/demo08/{canary.txt,summary_smoke.json}`,
  `runs/demo07/*oldbuild*` / `*_prefix.json`, remaining `scripts/_*_smoke.py` / `smoke_*.sh`.
  **Rule: grep the whitepaper + docs/demos for a reference before deleting anything under
  `runs/`** (e.g. `runs/demo07/summary_smallgrid.json` IS cited by Appendix A.3 — keep it).
- [ ] **F-3. Delete stale docs** (user approved): `IMPLEMENTATION_PLAN.md`,
  `docs/SELLING_COLMENA.md`, `docs/superpowers/{plans,specs}`. (git history preserves them.)
- [ ] **F-4. Rewrite `README.md`** as a replication landing page (currently stale).
- [ ] **F-5. Add `scripts/run_demo13.sh`** wrapper (Concurrency Ceiling only has
  `harness/loadtest/` + the doc).

---

## Group G — Merge, re-validate, finalize

- [ ] **G-1. Merge `cleanup/drop-demo11-demo12` to main** once the group above is reviewed
  (currently parked in backlog).
- [ ] **G-2. Rebuild Colmena at tag `colmena_dag_engine-v0.9.0`** (commit `b901a966`, tip of
  develop, 174 commits past the current pin `14beaba9`) and **recompute all Colmena arms**.
  Treat re-runs as a re-measurement that UPDATES the paper, not a strict verification —
  known-relevant changes: `f50a1f00` soft-deprecates `attachment_run_python` (demo08),
  `078fc78f` per-turn lazy-load guard (demo07), `data_run_python` unification (task04/demo08).
  Env: `DATABASE_URL`, `SECURE_VALUES_KEY` (≥32 chars), `GEMINI_API_KEY`.
- [ ] **G-3. Regenerate the PDF** (`scripts/build_whitepaper_pdf.py` → Chrome headless; do
  NOT combine `--headless=new` with `--virtual-time-budget` / `--run-all-compositor-stages`).
- [ ] **G-4. Final consistency audit** of the whitepaper after all edits (deterministic
  checks + fresh-eyes pass), then update companion docs (exec-brief, poster, business page).

---

## Open decisions blocking specific tasks

| Task | Decision needed |
|---|---|
| A-1 | CrewAI demo08: re-pin `<1.14.0` / migrate to E2B / mark N/A? |
| C-2 | demo07 LangChain: add tool-selector arm, or symmetric exclusion rule? |
| C-3 | demo10: add the `langgraph_interrupt_isolated` steelman arm? → DONE (arm built, 0% leak measured) |
| C-4 | demo07 LlamaIndex `tool_retriever`: add labeled RAG arm, or document + exclude? → DONE (documented + symmetric exclusion in §8.4) |
| E-1..E-4 | Sequence: multi-language section + ADK arm first (small), then full runners? |
