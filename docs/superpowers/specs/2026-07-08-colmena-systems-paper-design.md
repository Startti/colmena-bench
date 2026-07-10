# Design Spec — Colmena Systems Paper (arXiv)

**Date:** 2026-07-08
**Type:** Systems paper (arXiv preprint, English, single-column, ~10–14 pp.)
**Toolchain:** LaTeX via Tectonic (installed); sources under `paper/` (TBD in plan).
**Status:** Design approved; pending spec review → writing-plans.

---

## 1. Positioning and central contribution

**Type.** A *systems paper*: the artifact under presentation is the **Colmena engine**. The
paper leads with the system's design and then evaluates whether the design delivers.
(Not a benchmark paper — the experiments are the *evaluation*, subordinate to the design.)

**Central contribution (the one idea).**
> Colmena **relocates production concerns — context lifecycle, credential handling,
> human-in-the-loop, retry — from per-application code into invariants that the engine
> enforces by construction.** The enabler is a **declarative execution model**: an agent
> is a DAG-as-data, and a single generic engine executes it, creating a boundary at which
> cross-cutting concerns are enforced once, for all agents, rather than re-implemented per
> agent.

**Role of the key finding (evidence, not weakness).** Our strongest new result — a
hand-rolled Google ADK arm (`artifacts_scrub`) that closes the entire context-cost gap —
is *evidence for* the thesis: competitors **can** achieve the properties, but only by
re-writing them in per-application code, because they lack the engine boundary. This
converts a would-be "Colmena is more efficient" claim (attackable) into "Colmena delivers
by engine invariant what others achieve only by hand-rolled per-app code" (defensible).

---

## 2. Structure (hybrid: foundation + self-contained concerns)

| # | Section | Owns exclusively (anti-repetition) |
|---|---|---|
| 1 | **Introduction** | Problem (prod. concerns left to per-app code, routinely omitted) → the system → **states the concern-relocation-to-invariants thesis** → contributions → roadmap |
| 2 | **Background & Related Work** | Agents-as-code vs declarative agent *definition* (Open Agent Spec, Auton, Daunis); context-management prior art (caching, RAG, summarization, MemGPT, dynamic tool loading); secure agent execution; benchmarking critique. **The gap:** prior declarative work addresses *authoring*; none relocates production *properties* to engine invariants |
| 3 | **The Colmena Execution Model** (Foundation) | DAG-as-data model + **the engine boundary** (agent is data → engine enforces cross-cutting concerns once for all agents) + Rust runtime & bindings + **deployment consequence** (add/change/rollback agents as config, not redeploy). The *enabler*, explained once |
| 4 | **Experimental Methodology** | **Provider-authoritative measurement** (LiteLLM proxy), frameworks under test, identical conditions, **quality guardrail definition**, **per-token price held constant** (measured variable = token *volume*), reproducibility. The shared measurement basis, stated once |
| 5 | **Concern I — Context as an Engine-Managed Resource** | *Design:* ephemeral attachments + binary tool-output scrubbing + history compaction + lazy tool-schema loading as defaults keyed off the graph. *Eval (EQ1):* the Context Tax |
| 6 | **Concern II — Credential Isolation** | *Design:* the credential invariant (no plaintext secret ever enters the model context), enforced on **inbound** (`secure_suspend`) and **outbound** (tool-result masking) paths. *Eval (EQ2):* binary leak result |
| 7 | **Concern III — Production Hardening as Declarative Config** | *Design:* durable HITL suspend/resume + critic-retry as graph structure; the authoring/deployment consequence. *Eval (EQ3):* capability pass/fail + code-volume analysis |
| 8 | **Limitations & Negative Results** | Speed/round-trips; concurrency (optional); **the central honest caveat** (invariants are achievable with code → contribution is default/enforcement, not exclusivity) |
| 9 | **Conclusion** | Synthesis of the thesis across the three concerns |
| — | **References / Appendix** | Full data tables, prompts, version pins |

**Evaluation reduced to THREE concerns** (down from four): Tools-at-Scale is **folded into
Concern I** as a facet of "context as an engine-managed resource" (attachments +
tool-outputs + tool-schemas), not a separate experiment.

---

## 3. Anti-repetition discipline (each thing stated once, referenced elsewhere)

1. **Thesis (default → engine invariant):** stated §1; its *enabler* explained §3;
   **instantiated** (not re-argued) in §5–§7 with each concern's specific code delta;
   generalized honestly in §8; synthesized §9.
2. **Provider-authoritative measurement:** explained only §4; concerns say "measured at the
   proxy (§4)".
3. **Quality guardrail:** criterion defined §4; each concern reports pass/fail in one line.
4. **Code volume:** appears as *evidence* per concern (the delta a competitor hand-rolls) +
   a brief synthesis; the honest *caveat* lives in §8.

---

## 4. The three concerns — content and verified data

### Concern I — Context as an Engine-Managed Resource (EQ1)
- **Scenario:** fixed deterministic 10-turn analyst session, identical for all frameworks.
  Two growth sources: the document (`Q3_2026_report.md`, ~3,024 tokens, 11 sections) re-sent,
  and **3 chart tool-outputs** (turns 2/5/8), each a fixed ~8,168-token opaque base64 blob.
- **Default result (N=12):** competitors 404k–452k input tokens; Google ADK 445,370;
  Colmena 39,085. Per-turn "staircase": a plain doc turn climbs 3.6k → 26k → 48k → 71k after
  each chart, localizing the cost to the **retained binary tool outputs** (not the document).
- **The closure (new, N=3):** ADK `artifacts_scrub` — hand-rolled tool that `save_artifact`s
  the PNG and returns a short handle (+ `load_artifacts` for the doc) → **27,904 / 30,011 /
  28,470 (mean 28,795)**, quality PASS; per-turn chart turns stay flat (~1.3–2.2k vs
  19k/75k/120k). Verified via the flat token curve (proxy spans are metadata-only, so token
  counts — not text grep — are the evidence).
- **Reading:** the gap is **fully closable in a competitor**, but only with ~15–20 LOC of
  per-tool application code; Colmena delivers it by engine default. **Default-vs-code.**
- **Figure (1, the key one):** three per-turn curves — ADK default (blowup), ADK scrub (flat),
  Colmena (flat).
- **Dropped as noise:** the doc-only ADK steelman (467,900) — redundant, since the per-turn
  staircase already proves tool outputs are the driver.

### Concern II — Credential Isolation (EQ2)
- **Invariant:** no plaintext secret ever enters the model context, enforced **inbound**
  (`secure_suspend`: collected secrets routed to the tool, never the LLM) and **outbound**
  (tool-result masking: `auth_token` scrubbed before re-entering context).
- **Result (N=3/cell, 6 cells/framework, proxy-audited binary leak):**
  Colmena **0/6 leaked**, delivered 6/6; crewai/google_adk/langchain/langgraph **6/6 leaked**,
  all deliver. **Fair:** same task, all deliver (Colmena doesn't dodge the leak by failing).
- **Honest steelman (required):** the hand-architected `langgraph_interrupt_isolated` arm
  reaches **0/6** too — a competitor *can* be safe, but only by hand-architecting out-of-band
  collection with `interrupt()`. Same default-vs-code thesis.

### Concern III — Production Hardening as Declarative Config (EQ3)
- **Design:** durable HITL suspend/resume + critic-retry expressed as declarative graph
  structure (not hand-rolled control flow); masking referenced as already covered in EQ2.
- **Eval:** capability pass/fail (correct refund decision, durable resume, critic gate) +
  **code-volume analysis** (what each competitor hand-rolls to match).
- **Deployment consequence:** modifying an agent is a **configuration change, not a code
  deploy** — reduces authoring surface, framed as an implication (see §6 below).

---

## 5. Honesty / framing decisions (locked)

1. **Per-token price is NOT a limitation.** Price per token is identical across frameworks
   (same model) — a constant, held in **Methodology (§4)**. Colmena's cost advantage is
   entirely **token volume**. A discussion note may observe that provider prompt-caching
   narrows the *dollar* gap (not the token gap). Do **not** frame it as "no price advantage."
2. **Speed:** per-call latency at parity (hello-world: Colmena 761 ms vs LangChain 738 ms);
   Colmena makes more round-trips per session (18 vs 13 — lazy + compaction), so it is **not
   faster per session**. Honest trade-off, in §8.
3. **Concurrency (optional, user's call):** Colmena Serve serializes within a process
   (~2.6 rps vs ~50 rps async LangGraph); scaling model is horizontal (many distinct agents)
   with ~4× lower RAM. Include as a brief honest §8 note only if kept.
4. **The "config vs code" claim — calibrated.** Sellable kernel (evidence-anchored):
   *production concerns move from per-application code each team writes, tests, and maintains
   to engine-enforced configuration, eliminating per-agent re-implementation of cross-cutting
   safety logic, and turning an agent change into a configuration change rather than a code
   deploy.* Do **NOT** claim "no code" (agent logic + custom tools still require engineering)
   or "no development team needed" (unmeasured org/economic claim — reads as marketing).
   Scope every such statement to the **cross-cutting concerns**, not the whole agent.

---

## 6. Out of scope (explicitly dropped, to keep the paper tight)

- **Sandboxed Code Execution** experiment (was parity 0.95 across all — no signal, adds noise).
- **Multi-language portability (E-4)** as a section (→ at most one sentence in §3, if at all).
- **Doc-only ADK steelman** as its own result (folded away; per-turn staircase subsumes it).
- **Any "no-code / no dev team" claim** (too strong; unmeasured).
- New framework runners (Pydantic AI, OpenAI Agents SDK, Mastra) as evaluation arms — they
  belong to harness portability, not this paper's evaluation.

---

## 7. Open items for the writing plan

- Decide concurrency inclusion (§8) — pending user.
- Title (working): "Agents as Configuration: Relocating Production Concerns to Engine-Enforced
  Invariants" — refine at the end.
- LaTeX project layout (`paper/main.tex`, per-section files, `refs.bib`), build via Tectonic.
- Figure/table asset list: Fig. 1 (three per-turn context curves); Table (context totals);
  Table (credential-leak matrix incl. steelman); Table (hardening capability + LOC).
- Provenance: all Colmena numbers from build `colmena_dag_engine-v0.9.0`; ADK `artifacts_scrub`
  N=3 committed (`968f5e7`); context/credential data from `runs/demo05`, `runs/demo10`.
