# Colmena Systems Paper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write a tight arXiv systems paper on the Colmena engine whose thesis is that Colmena relocates production concerns (context, credentials, hardening) from per-application code into engine-enforced invariants, enabled by a declarative DAG-as-data execution model.

**Architecture:** LaTeX project under `paper/`, one `\input` file per section, built with Tectonic. Written body-first (Foundation → 3 concern sections → Methodology → Related Work → Limitations), then Introduction, Conclusion, and Abstract last so they reflect the settled body. One commit per section; each section gated by a review checklist before moving on.

**Tech Stack:** LaTeX (`article`, single-column), Tectonic 0.16.9 (installed at `/opt/homebrew/bin/tectonic`), `biblatex`+`biber` for references, `booktabs`/`graphicx`/`hyperref`/`siunitx`.

**Source of truth:** the approved spec `docs/superpowers/specs/2026-07-08-colmena-systems-paper-design.md`. Read it before starting any section.

## Global Constraints

- **Language:** English, formal academic register. Precise, restrained, evidence-first prose.
- **Positioning:** systems paper (artifact = the Colmena engine). Design leads; experiments are the *evaluation*.
- **Central thesis (verbatim compass):** "Colmena relocates production concerns — context lifecycle, credential handling, human-in-the-loop, retry — from per-application code into invariants the engine enforces by construction; the declarative DAG-as-data model is the enabler."
- **Anti-repetition (enforced per section):** thesis stated §1, enabler explained §3, instantiated (not re-argued) in §5–§7, generalized in §8, synthesized §9. Provider-authoritative measurement explained only §4; other sections say "measured at the proxy (§4)". Quality-guardrail criterion defined only §4; each concern reports pass/fail in one line. Code-volume is per-concern evidence + a brief synthesis; its honest caveat lives only in §8.
- **Locked honesty rules:** (a) per-token price is a held-constant in §4, NEVER a limitation; cost advantage is token *volume*. (b) credential result presented WITH its `langgraph_interrupt_isolated` steelman. (c) "config vs code" scoped to cross-cutting concerns — NEVER "no-code" or "no development team". (d) not faster per session (more round-trips). (e) concurrency out of scope — do not mention.
- **Provenance:** all Colmena numbers from build `colmena_dag_engine-v0.9.0`; ADK `artifacts_scrub` from commit `968f5e7`; context data `runs/demo05/report/agg_n12.json`; credential data `runs/demo10/summary.csv`.
- **Title (locked):** "Agents as Configuration: Relocating Production Concerns to Engine-Enforced Invariants."
- **Every claim cites either a table/figure in this paper or a source in `refs.bib`.** No unsupported assertion.
- **Build must stay green:** after each section, `tectonic paper/main.tex` compiles with no errors.

---

## File Structure

- Create `paper/main.tex` — documentclass, packages, title/authors, `\input` of each section, bibliography.
- Create `paper/refs.bib` — all references (BibLaTeX entries).
- Create `paper/sections/03-execution-model.tex` — Foundation.
- Create `paper/sections/05-context.tex` — Concern I (Context).
- Create `paper/sections/06-credentials.tex` — Concern II (Credentials).
- Create `paper/sections/07-hardening.tex` — Concern III (Hardening).
- Create `paper/sections/04-methodology.tex` — Methodology.
- Create `paper/sections/02-related-work.tex` — Background & Related Work.
- Create `paper/sections/08-limitations.tex` — Limitations & Negative Results.
- Create `paper/sections/01-introduction.tex` — Introduction.
- Create `paper/sections/09-conclusion.tex` — Conclusion.
- Create `paper/sections/00-abstract.tex` — Abstract.
- Create `paper/figures/context_curves.*` — Fig. 1 (built in Task 4).
- Create `paper/.gitignore` — ignore `main.pdf`, `*.aux`, `*.bbl`, `*.bcf`, `*.run.xml`, `*.log`, `build/`.

Each section is its own file so it can be drafted, compiled, reviewed, and committed independently.

---

### Task 0: Scaffold the LaTeX project (compiles to an empty-but-valid PDF)

**Files:**
- Create: `paper/main.tex`, `paper/refs.bib`, `paper/.gitignore`, and empty `paper/sections/*.tex` stubs (one `\section{...}` heading each).

**Interfaces:**
- Produces: a compiling `paper/main.tex` that `\input`s all ten section files in reading order (01→09 plus abstract); later tasks only fill the section files.

- [ ] **Step 1: Create `paper/main.tex`**

```latex
\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{siunitx}
\usepackage{amsmath}
\usepackage[hidelinks]{hyperref}
\usepackage[backend=biber,style=numeric-comp,sorting=none]{biblatex}
\addbibresource{refs.bib}

\title{Agents as Configuration: Relocating Production Concerns to\\ Engine-Enforced Invariants}
\author{}
\date{}

\begin{document}
\maketitle
\input{sections/00-abstract}
\input{sections/01-introduction}
\input{sections/02-related-work}
\input{sections/03-execution-model}
\input{sections/04-methodology}
\input{sections/05-context}
\input{sections/06-credentials}
\input{sections/07-hardening}
\input{sections/08-limitations}
\input{sections/09-conclusion}
\printbibliography
\end{document}
```

- [ ] **Step 2: Create stub section files**

Each `paper/sections/NN-name.tex` contains only its heading, e.g. `paper/sections/01-introduction.tex`:
```latex
\section{Introduction}
\label{sec:intro}
```
`00-abstract.tex` contains `\begin{abstract}\end{abstract}`. Create all ten stubs with the headings: Introduction, Background and Related Work, The Colmena Execution Model, Experimental Methodology, Context as an Engine-Managed Resource, Credential Isolation, Production Hardening as Declarative Configuration, Limitations and Negative Results, Conclusion.

- [ ] **Step 3: Create `paper/refs.bib` with a placeholder-free seed**

Seed with the entries the spec's Related Work names (fill full fields): `daunis2025`, `amini2025` (Open Agent Spec), `cao2026` (Auton), `lewis2020` (RAG), `packer2023` (MemGPT), `gansun2025` (dynamic tool loading), plus Anthropic and Google caching docs as `@online`. Use the URLs already cited in `docs/articles/colmena-whitepaper.md` References section.

- [ ] **Step 4: Create `paper/.gitignore`**

```
main.pdf
build/
*.aux
*.bbl
*.bcf
*.blg
*.log
*.out
*.run.xml
```

- [ ] **Step 5: Compile and verify**

Run: `cd paper && tectonic main.tex`
Expected: `main.pdf` written, exit 0, no errors (undefined citations are fine at this stage).

- [ ] **Step 6: Commit**

```bash
git add paper/main.tex paper/refs.bib paper/.gitignore paper/sections
git commit -m "paper: scaffold LaTeX project (compiles)"
```

---

### Task 1: §3 The Colmena Execution Model (Foundation)

**Files:**
- Modify: `paper/sections/03-execution-model.tex`

**Content to write (the argument, in order):**
1. **The declarative model.** An agent in Colmena is a declarative JSON document — a DAG of typed nodes and edges — not a program. Show a small, real node/edge fragment (source: `runners/colmena/runner/dags/*.json`, e.g. the refund or secrets DAG). Define "node types" (LLM, tool, `secure_suspend`, `python_script`, `data_run_python`).
2. **The generic engine and the boundary.** A single Rust engine (`dag_engine::api::run_dag`) executes *any* such document. Because the agent is data, the engine sits at a boundary where it enforces cross-cutting concerns once, for every agent — this is the enabler for the invariants in §5–§7. State this as the paper's mechanism, not a feature list.
3. **Runtime and bindings.** Rust core; PyO3/napi bindings expose `run_dag` to Python and TypeScript (one sentence — evidence that the engine is the unit, callable from multiple hosts). Do not make this a portability section.
4. **Deployment consequence.** An agent is added, changed, or rolled back as configuration (data), not a code redeploy. Frame as an implication of the model. Scope to cross-cutting concerns; do NOT claim "no code" or "no developers" (Global Constraint c).

**Anti-repetition:** this is the ONLY place the execution model and the "engine boundary" are explained. Later sections reference it as "the engine boundary (\S\ref{sec:model})".

- [ ] **Step 1: Draft the section prose** in `03-execution-model.tex` following the four points above, with one real DAG fragment (`lstlisting` or `verbatim`, keep it short). Add `\usepackage{listings}` to `main.tex` if used.
- [ ] **Step 2: Compile** — `cd paper && tectonic main.tex` → exit 0.
- [ ] **Step 3: Review checklist (all must hold):**
  - Explains DAG-as-data + the engine boundary as the *enabler* (not a feature list).
  - Deployment consequence scoped to cross-cutting concerns; no "no-code/no-devs".
  - No experiment numbers here (design only).
  - Formal register; every technical claim points to a real mechanism/file.
- [ ] **Step 4: Commit** — `git add paper/sections/03-execution-model.tex paper/main.tex && git commit -m "paper: §3 Colmena execution model (foundation)"`

---

### Task 2: §5 Context as an Engine-Managed Resource (Concern I)

**Files:**
- Modify: `paper/sections/05-context.tex`
- (Figure produced in Task 4; reference it as `\ref{fig:context}` now.)

**Exact data to cite (from `runs/demo05/report/agg_n12.json`, N=12, and commit `968f5e7`, N=3):**
- Scenario: fixed 10-turn analyst session; document `Q3_2026_report.md` ≈ 3{,}024 tokens, 11 sections; one tool `generate_chart` returning a fixed ≈ 8{,}168-token opaque base64 blob; 3 chart turns (turns 3, 6, 9 in 1-indexed / 2,5,8 in 0-indexed).
- Default totals (input tokens, 10-turn session): Colmena **39{,}085**; Google ADK **445{,}370**; competitor range **404{,}095–452{,}359** (LangGraph 404{,}095; LlamaIndex 419{,}934; Google ADK 445{,}370; LangChain 452{,}158; CrewAI 452{,}359). Cost: Colmena \$0.018 vs \$0.125–\$0.142.
- Per-turn staircase (LangChain, to show the mechanism): a plain document turn costs ≈ 3.6k before any chart, then ≈ 26k after chart 1, ≈ 48k after chart 2, ≈ 71k after chart 3 — localizing the cost to the retained binary tool outputs, not the document.
- The closure (new result): ADK `artifacts_scrub` (hand-rolled tool `save_artifact`s the PNG + returns a handle; `load_artifacts` for the document) → **27{,}904 / 30{,}011 / 28{,}470**, mean **28{,}795** (N=3), quality PASS; per-turn chart turns flat (≈ 1.3–2.2k vs the default arm's 19k/75k/120k). Verified via the token curve (proxy spans are metadata-only; token counts, not text, are the evidence).

**Content (argument order):**
1. **Design.** The engine manages the context window as a resource: ephemeral attachments, binary tool-output scrubbing, history compaction, lazy tool-schema loading — defaults keyed off the graph. (Reference §3 boundary; do not re-explain the model.)
2. **Default tax (EQ1).** Table of totals + the staircase; attribute the escalation to retained binary tool outputs.
3. **The closure.** The `artifacts_scrub` result + Fig. 1 (three per-turn curves). State plainly: the gap is fully closable in a competitor, but only with ≈ 15–20 LOC of per-tool application code.
4. **Reading (one paragraph).** Default-vs-code: Colmena delivers by engine default what the competitor achieves only by hand-rolled per-tool code. One line: quality PASS for all (guardrail defined in §4).

**Anti-repetition:** do NOT restate the proxy methodology or the guardrail definition (cite §4). Do NOT discuss the doc-only ADK steelman (dropped). The default-vs-code meta-claim is stated once here as this concern's instantiation.

- [ ] **Step 1: Draft** `05-context.tex` per the four points with the exact numbers above; insert the totals table (`booktabs`) and reference `\ref{fig:context}`.
- [ ] **Step 2: Compile** → exit 0 (figure ref may be undefined until Task 4 — acceptable; note it).
- [ ] **Step 3: Review checklist:**
  - Every number matches the values above exactly.
  - Attribution to tool outputs (not the document) is explicit and tied to the staircase.
  - `artifacts_scrub` framed as evidence (default-vs-code), not a Colmena weakness.
  - No proxy/guardrail re-explanation; cites §4.
- [ ] **Step 4: Commit** — `git commit -am "paper: §5 context as engine-managed resource"`

---

### Task 3: §6 Credential Isolation (Concern II)

**Files:**
- Modify: `paper/sections/06-credentials.tex`

**Exact data (from `runs/demo10/summary.csv`, N=3/cell, 6 cells/framework, proxy-audited binary leak):**
- Colmena: secret_leaked **0/6**, delivered **6/6**.
- crewai, google_adk, langchain, langgraph (idiomatic default): secret_leaked **6/6**, delivered **6/6**.
- `langgraph_interrupt_isolated` (hand-architected steelman): secret_leaked **0/6**, delivered **6/6**.

**Content (argument order):**
1. **The invariant.** No plaintext secret ever enters the model context, enforced on the inbound path (`secure_suspend`: collected credentials routed to the tool, never the LLM) and the outbound path (tool-result masking: the `auth_token` field scrubbed before re-entering context). One invariant, two enforcement points.
2. **Result (EQ2).** Leak matrix: 0% (Colmena) vs 100% (four competitor defaults). Emphasize fairness: same task, all frameworks deliver (Colmena does not dodge the leak by failing the task); criterion is binary and proxy-audited.
3. **Honest steelman (required).** `langgraph_interrupt_isolated` reaches 0% too — a competitor *can* be safe, but only by hand-architecting out-of-band collection with `interrupt()`. Same default-vs-code thesis as §5.

**Anti-repetition:** masking is owned here (both secret paths consolidated). Do not re-explain the proxy audit mechanism beyond one clause citing §4.

- [ ] **Step 1: Draft** `06-credentials.tex` with the leak matrix table and the three points.
- [ ] **Step 2: Compile** → exit 0.
- [ ] **Step 3: Review checklist:**
  - 0/6 vs 6/6 numbers exact; delivery 6/6 for all stated (the fairness point).
  - Both enforcement points (inbound + outbound) present; no overlap left for §7.
  - The `langgraph_interrupt_isolated` steelman is included and framed as default-vs-code.
- [ ] **Step 4: Commit** — `git commit -am "paper: §6 credential isolation"`

---

### Task 4: Figure 1 — three per-turn context curves

**Files:**
- Create: `paper/figures/context_curves.pdf` (+ the generator script `paper/figures/make_context_curves.py`).

**Data (per-turn input tokens, 10 turns):**
- ADK default: `[3351, 3838, 19224, 27952, 26367, 75196, 48830, 48878, 120341, 71395]`
- ADK artifacts_scrub (pass 1): `[3948, 4590, 1651, 5096, 1003, 2161, 1142, 5642, 1314, 1357]`
- Colmena: `[4901, 4056, 3502, 4398, 1833, 5213, 2955, 5682, 4250, 2296]`

- [ ] **Step 1: Write `make_context_curves.py`** (matplotlib) plotting the three series vs turn index (1–10), mark chart turns (3,6,9), y-axis "input tokens", legend, save `context_curves.pdf`. Use the `.venv-bench` python (has matplotlib) or `runs/demo05` plotting env.
- [ ] **Step 2: Generate** — `cd paper/figures && ../../.venv-bench/bin/python make_context_curves.py` → `context_curves.pdf` exists.
- [ ] **Step 3: Insert the figure** into `05-context.tex` with `\begin{figure}...\includegraphics{figures/context_curves}...\label{fig:context}\end{figure}` and a caption stating the ADK-default blowup vs the two flat curves.
- [ ] **Step 4: Compile** → exit 0, `\ref{fig:context}` resolves.
- [ ] **Step 5: Commit** — `git add paper/figures paper/sections/05-context.tex && git commit -m "paper: Fig. 1 context per-turn curves"`

---

### Task 5: §7 Production Hardening as Declarative Configuration (Concern III)

**Files:**
- Modify: `paper/sections/07-hardening.tex`

**Data (from `runs/demo06` refund experiment):** capabilities scored pass/fail — correct refund decision under policy, durable HITL suspend/resume across a fresh process, critic-retry gate. Colmena expresses all as declarative graph structure; competitors hand-roll them. Include the code-volume comparison (LOC each framework writes to match) as this concern's evidence.

**Content (argument order):**
1. **Design.** Durable HITL suspend/resume + critic-retry as declarative graph structure (a `secure_suspend`/suspend node + a cyclic critic edge), not hand-rolled control flow. Masking already covered in §6 — reference it, do not re-argue.
2. **Evaluation (EQ3).** Capability pass/fail table + the code-volume comparison (Colmena config vs competitor hand-rolled LOC).
3. **Deployment consequence (calibrated).** Modifying an agent is a configuration change, not a code deploy; reduces authoring surface for cross-cutting concerns. NEVER "no-code" / "no development team" (Global Constraint c).

- [ ] **Step 1: Draft** `07-hardening.tex` with the capability table + LOC table.
- [ ] **Step 2: Compile** → exit 0.
- [ ] **Step 3: Review checklist:**
  - Masking referenced (not re-argued) — points to §6.
  - Config-vs-code claim scoped to cross-cutting concerns; no over-claim.
  - Capability results are pass/fail with the actual criteria named.
- [ ] **Step 4: Commit** — `git commit -am "paper: §7 production hardening as configuration"`

---

### Task 6: §4 Experimental Methodology

**Files:**
- Modify: `paper/sections/04-methodology.tex`

**Content (argument order):**
1. **Provider-authoritative measurement.** All LLM calls route through one shared LiteLLM proxy; token/cost figures are read at the proxy, not self-reported. Header-based per-run span correlation; Colmena's header-less session-delta method (one clause).
2. **Frameworks and conditions.** Colmena (Rust) + CrewAI, LangChain, LangGraph, LlamaIndex, Google ADK (Python); identical model (`gemini-2.5-flash`), temperature 0, same proxy, same task inputs; version pins → appendix.
3. **Per-token price held constant.** State explicitly: price per token is identical across frameworks (same model); the measured variable is token *volume*, not price. (Global Constraint a — this is the ONLY place price is discussed; never a limitation.)
4. **Quality guardrail.** Define the criterion once: designated-turn substring checks (+ an LLM-judge score in the appendix). Each concern reports pass/fail against this.
5. **Reproducibility.** Build provenance (`colmena_dag_engine-v0.9.0`), run scripts, harness.

**Anti-repetition:** this is the sole home of proxy methodology, price-constant, and guardrail definition.

- [ ] **Step 1: Draft** `04-methodology.tex` per the five points.
- [ ] **Step 2: Compile** → exit 0.
- [ ] **Step 3: Review checklist:**
  - Price-per-token framed as a held constant (measured variable = volume); never a disadvantage.
  - Guardrail criterion defined once, concretely.
  - Proxy method explained once; concerns can now cite it.
- [ ] **Step 4: Commit** — `git commit -am "paper: §4 methodology"`

---

### Task 7: §2 Background and Related Work

**Files:**
- Modify: `paper/sections/02-related-work.tex`

**Content:** (a) agents-as-code vs declarative agent *definition* — Open Agent Spec (`amini2025`), Auton (`cao2026`), Daunis (`daunis2025`); (b) context-management prior art — provider caching (`@online` Anthropic/Google), RAG (`lewis2020`), summarization, MemGPT (`packer2023`), dynamic tool loading (`gansun2025`); (c) secure agent execution / secret handling; (d) benchmarking critique (self-reported vs provider-authoritative). **The gap (thesis hook):** prior declarative work addresses *authoring*; none relocates production *properties* to engine invariants.

- [ ] **Step 1: Draft** `02-related-work.tex`; ensure every `\cite` has a complete `refs.bib` entry.
- [ ] **Step 2: Compile** → exit 0, no undefined citations.
- [ ] **Step 3: Review checklist:** the "gap" paragraph positions THIS paper's contribution; no citation is a bare URL without author/title/year.
- [ ] **Step 4: Commit** — `git commit -am "paper: §2 background and related work"`

---

### Task 8: §8 Limitations and Negative Results

**Files:**
- Modify: `paper/sections/08-limitations.tex`

**Content (exactly these, no more):**
1. **Speed / round-trips.** Per-call latency at parity (hello-world: Colmena 761 ms vs LangChain 738 ms); Colmena makes more round-trips per session (≈ 18 vs 13 — lazy loading + compaction), so it is not faster per session. Honest trade-off.
2. **The central caveat.** The invariants are achievable with code (evidenced by `artifacts_scrub` in §5 and `langgraph_interrupt_isolated` in §6); the contribution is the engine default/enforcement, not exclusivity.
3. (Cost is NOT here — it is a held-constant in §4. Concurrency is NOT here — out of scope.)

- [ ] **Step 1: Draft** `08-limitations.tex` with exactly the two items.
- [ ] **Step 2: Compile** → exit 0.
- [ ] **Step 3: Review checklist:** no per-token-price limitation; no concurrency; the central caveat generalizes §5/§6 honestly.
- [ ] **Step 4: Commit** — `git commit -am "paper: §8 limitations and negative results"`

---

### Task 9: §1 Introduction (written after the body)

**Files:**
- Modify: `paper/sections/01-introduction.tex`

**Content (argument order):**
1. Problem: production agents accrue hidden context/credential/hardening costs that mainstream frameworks leave to per-application code, routinely omitted.
2. The system: Colmena — a declarative engine that relocates these concerns to engine-enforced invariants.
3. **State the thesis (the verbatim compass).** 
4. Contributions list (the engine model §3; the provider-authoritative evaluation §4; the three concern results §5–§7; the honest default-vs-code account §8).
5. Roadmap sentence.

- [ ] **Step 1: Draft** `01-introduction.tex`; ensure every forward reference (§3–§8) resolves.
- [ ] **Step 2: Compile** → exit 0.
- [ ] **Step 3: Review checklist:** thesis stated once and matches the compass; contributions map 1:1 to sections that exist; no result numbers duplicated from the body beyond one headline each.
- [ ] **Step 4: Commit** — `git commit -am "paper: §1 introduction"`

---

### Task 10: §9 Conclusion + Abstract + final assembly

**Files:**
- Modify: `paper/sections/09-conclusion.tex`, `paper/sections/00-abstract.tex`

**Content:**
- Conclusion: synthesize the thesis across the three concerns; one forward-looking sentence on engine-enforced invariants as a design stance for agent frameworks. No new claims.
- Abstract (≤ 200 words): problem → the engine and its thesis → the three results with headline numbers (context 39k vs 404–452k with the closable-only-by-code finding; credentials 0% vs 100% with the steelman; hardening as config) → the honest scope (default/enforcement, not exclusivity).

- [ ] **Step 1: Draft** conclusion and abstract.
- [ ] **Step 2: Full compile** — `cd paper && tectonic main.tex`; expected: exit 0, zero undefined references/citations, `main.pdf` produced.
- [ ] **Step 3: Whole-paper review checklist:**
  - Anti-repetition holds end-to-end (proxy/guardrail/price each stated once; thesis instantiated not repeated).
  - Every number traces to a run artifact; every citation resolves.
  - Honesty rules all satisfied (price-constant, credential steelman, config-vs-code scoped, not-faster, no concurrency).
  - Formal register throughout.
- [ ] **Step 4: Commit** — `git add paper && git commit -m "paper: conclusion, abstract, final assembly"`

---

## Self-Review (author runs before handoff)

- **Spec coverage:** every spec section (§1–§7 of the spec) maps to a task above — positioning/thesis (Tasks 9,0), structure (all), 3 concerns (Tasks 2,3,5), anti-repetition (per-task checklists), honesty decisions (Tasks 6,3,5,8), out-of-scope (enforced by omission).
- **Placeholder scan:** the plan carries exact numbers and file paths; no "TBD" in section content. The only deferred artifact is Fig. 1, produced in Task 4 before §5 is finalized.
- **Consistency:** section file names and `\label`s are consistent across tasks (`sec:model`, `fig:context`, §4 citations).
