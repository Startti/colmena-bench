# Colmena Benchmark Articles — Design

**Status:** Approved (brainstorm complete 2026-06-23)
**Author:** daniel + Claude

---

## 1. Goal

Produce **two** evidence-based articles from the completed `colmena-bench` suite, both
drawing on the same provider-authoritative data and both honest enough to survive a
skeptical technical buyer:

1. **Technical whitepaper** (long-form) — methodology, per-demo deep dives with charts,
   a named honest-limitations section, full reproduction. Audience: skeptical eng lead.
2. **Business exec brief** (short, visual-first) — the same numbers reframed as
   cost / risk / effort. Audience: decision-maker.

One evidence base, two renderings. The business brief links back to the whitepaper for
full methodology and sources.

## 2. Governing principles

- **Honesty above all.** Every number is provider-authoritative (captured at the shared
  LiteLLM proxy, not framework self-report). We lead with limitations where they exist.
  We do not feature ties as wins.
- **Spine = context efficiency is the hero.** Walk/lead order: Demo 05 → Demo 10 →
  Demo 06 → Demo 08 → Demo 07. Strongest single number leads.
- **Rendering rule:**
  - *Technical whitepaper = precision-first.* Text-heavy "concept graphics" become
    **tables or prose**. Only genuine quantitative trends stay as plots (cumulative-token
    line, multiplier curve, token/USD bars, tokens-vs-tools).
  - *Business brief = visual-first.* Keep the punchy colored graphics (flat-vs-climbing
    line, 0/100 leak bars, green/red capability grid).
  - Same result → two renderings (e.g. Demo 06 capability: ✓✗ table in whitepaper,
    colored grid in brief; Demo 10 leak: table in whitepaper, 0/100 bars in brief).

## 3. Demo decisions (output of the chart-by-chart walk)

### Demo 05 — Context Tax (HERO)
Headline: **37,619 vs 404k–452k input tokens over 10 turns (~12×); ~7.6× cheaper
($0.018 vs $0.13–$0.14); quality preserved.** N=12, mean±std.
- **Whitepaper plots:** `2_line_cumulative` (anchor), `5_multiplier_curve`,
  `1_bar_total_tokens`, `4_bar_usd`, `13_bar_quality`, `8_stacked_composition` (mechanism),
  `7_loc_bar` → honesty section, `10_line_calls` → honesty (Colmena makes ~19 vs 13 calls,
  still wins).
- **Business brief:** `2_line_cumulative` + `4_bar_usd`.
- **Cut:** `6_quadrant`, `11_bar_ram`. **Optional appendix:** `3`, `9`, `12`, `14`.

### Demo 10 — secure_suspend (HERO, security)
Headline: **Colmena 0% secret leak; all 5 competitors 100%** (both variants).
- **Variants explained in prose:** `collect` = idiomatic mid-conversation credential
  collection (Colmena returns opaque `<sv_*>` handles → no leak; competitors put the
  pasted secret in transcript → leak). `echo` = a tool echoes the secret back (Colmena
  re-masks before re-entry; competitors pass it through; moot for competitors who already
  leaked at collect).
- **Whitepaper:** leak-rate **table** (0% vs 100%, n=3/cell) + capability **table**.
  Honesty notes: counterfactual/capability demo at small scale; fairness guard
  `delivered_to_api=true` (Colmena still delivers the secret — not "safe by refusing to
  work").
- **Business brief:** the colored 0/100 `leak_rate` bars (Risk card).

### Demo 06 — Refund Agent (production capability)
Distinct job vs Demo 10: the **production-hardening capability matrix**, not a repeat of
masking. Headline: graph + durable HITL + critic-retry + masking in one hardened agent;
**LangGraph is the honest near-peer (native on three; red only on masking)** → masking is
the lone differentiator. LOC is explicitly **not** a win (Colmena 120 code + 115 config vs
competitors 93–171; LangGraph highest at 171).
- **Whitepaper:** `capability_matrix` as a **native/DIY ✓✗ table** (LangGraph masking gap
  called out) + masking counterfactual **table** (naive variant leaks on all 5; caveat: a
  counterfactual of the naive variant, not a failure of the hardened impls) +
  `loc_code_vs_config` → honesty section.
- **Business brief:** the colored capability **grid** (Effort card).
- Masking leak cross-references Demo 10 (no repeat).

### Demo 08 — Sandboxed Code Execution (full supporting)
Headline (with honesty built in): forbidden filesystem read attempted in each framework's
code tool — **Colmena CONTAINED; langchain + langgraph LEAKED; llamaindex/crewai/google_adk
contained for different reasons.** NOT "Colmena uniquely safe."
- **Whitepaper (full supporting section):** `security_probe` as a **table**
  (framework | result | mechanism) + two honest points: (1) two popular frameworks run
  model code unsandboxed by default; (2) Colmena contains it declaratively in-process,
  *conceding* crewai's Docker is stronger OS-level isolation. `analytics_parity` (≈0.97
  all) → honesty (no accuracy win).
- **Business brief:** one-liner in the Risk card ("2 of 5 popular frameworks execute
  untrusted code unsandboxed by default"). No standalone visual.

### Demo 07 — Many Tools (supporting, context/tools axis)
Headline: **colmena-lazy ~1.7–1.9× fewer cumulative tokens** than every competitor at
identical accuracy (1.00); 200-tool probe **22k vs 44k–103k (~2–4.7×)**.
- **Honest caveat:** in multi-turn, most of the framework win is conversation-memory
  compaction (helps lazy AND eager); lazy-specific increment ~1.11× over eager at 30 tools,
  grows with tool count. The single-turn `tokens_vs_tools_hard` chart isolates lazy
  (eager ≈ competitor pack); the multi-turn chart shows the combined effect.
- **Whitepaper plots:** `tokens_vs_tools_hard` (hero, isolates lazy),
  `session_cum_tokens_vs_turn` (multi-turn), `accuracy_vs_tools_hard` → honesty.
- **Business brief:** `tokens_vs_tools_hard` only.
- **Cut:** `session_selection_vs_turn`, `session_cum_tokens_at_turn10_bar`.
  **Appendix:** `tokens_at_200_bar`.

### Demo 09 — Skills — **CUT from both articles**
Reason: vs naive it re-tells the context-efficiency win already made twice (05, 07); vs RAG
(the legitimate alternative) it is a **tie** on tokens/accuracy (RAG slightly lower), edge
is only "no vector DB" (unmeasured DX). Featuring it invites a "why not RAG?" question we
lose on the numbers and dilutes the strong demos. Demo still exists in repo + memory.
Mentioned once, briefly, in the whitepaper honesty section as a tie we don't claim.

### Task 04 — CSV analytics — whitepaper honesty exhibit only
A *strategy* result (SQL-tool "expert" beats raw-CSV "naive" regardless of framework) that
doubles as an honesty exhibit: **Colmena expert 88–92% vs competitors ~100%**, because the
same rolling-summary compaction that wins Demo 05 truncates large mid-conversation tool
tables here (same mechanism, opposite sign; tunable via `KEEP_RECENT` / `recall_history`).
- **Whitepaper §9 only:** `tokens_asymptote` (strategy point) + `accuracy` (the trade-off).
- **Not in the business brief.**

### Demos 11 & 12 — dropped, named in the honesty section
Both honestly dropped (naive matched Colmena: #11 small/known API spec; #12 temp-0 policy
routing). Named in §9 as evidence of the honesty discipline.

## 4. Document structure

### Technical whitepaper
1. Executive summary — hero numbers + one-line pitch
2. Why this benchmark exists + honesty stance
3. Methodology — proxy, 6 frameworks, pinned versions, identical model/temp, Colmena
   session-delta measurement
4. Hero: Demo 05 (context tax)
5. Hero: Demo 10 (secret handling)
6. Demo 06 (production capability matrix)
7. Demo 08 (sandbox, full supporting)
8. Demo 07 (lazy tools / tool axis)
9. **What Colmena does NOT win** — LOC on simple agents, no parallelism, no per-token price
   advantage, Task 04 accuracy trade-off, dropped #11/#12, Demo 09 RAG-tie note
10. Reproduction
- Appendix A — full data tables
- Appendix B — prompts used (system messages, naive prompt-builders, DAG configs)
- Appendix C — references (Colmena repo + commit, bench repo, 5 frameworks + pinned
  versions, LiteLLM proxy, model/provider, external sources)

### Business exec brief
1. Headline — cost ↓, secrets safe, less code to maintain
2. Three outcome cards:
   - **Cost** — Demo 05 (flat-vs-climbing line + USD bar)
   - **Risk** — Demo 10 (0/100 colored leak bars) + Demo 08 one-liner
   - **Effort** — Demo 06 (green/red capability grid)
3. Credibility — independent proxy, fair conditions, idiomatic competitors
4. Honest limitations — one line (builds trust)
5. Next step / CTA + link to whitepaper

## 5. Source material
- Demo docs in `docs/demos/` (figures already written there).
- Charts in `runs/demo0{5,6,7,8}/...` and `runs/task04/...` (paths per manifest above).
- `docs/SELLING_COLMENA.md` — existing pitch spine (stale "to build" statuses; refresh).
- Honesty memories: `demo11-api-explorer-dropped`, `demo12-router-dropped`,
  `colmena-real-differentiators`.

## 6. Out of scope (YAGNI)
- Re-running any demo or regenerating charts (use what shipped).
- New plots beyond the table-renderings of existing concept graphics.
- Slides / PDF export (separate task if wanted).

## 7. Success criteria
1. Both documents written, every number traceable to a demo doc / run artifact.
2. Whitepaper has a named honesty section carrying LOC, parallelism, Task 04 trade-off,
   dropped #11/#12, Demo 09 tie.
3. Rendering rule applied (tables in whitepaper, colored visuals in brief).
4. Appendices B (prompts) and C (references) present.
5. Demo 09 absent from both; Task 04 whitepaper-honesty-only.
