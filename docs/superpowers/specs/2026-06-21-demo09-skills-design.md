# Demo #9 — Skills / Progressive Knowledge Loading — Design

**Status:** Draft for review
**Date:** 2026-06-21
**Author:** daniel + Claude
**Pairs with:** Demo #10 (`secure_suspend`) — shipped together as the next whitepaper tranche.

---

## 0. DESIGN PIVOT (2026-06-22) — extractive policy QA, not computation-over-data

The original design (below, §2–§6) made each answer a **number computed from the
`orders_synthetic` dataset**. During implementation (after T9) we found a fatal gap:
the hypothesis is about **knowledge navigation**, but computing over data requires the
agent to *have* the data — which no arm provides — and it confounds the accuracy signal
with code/arithmetic ability (already Demo #8's job). We pivoted to the canonical Skills
use case:

- **Domain:** a fictional insurer, **"Colmena Seguros"**. Each pack is a **policy
  document** (product line, e.g. `colmena-hogar-premium`); nested references are perils
  (`water-damage` → `residential`/`commercial`) whose leaves hold **company-specific,
  non-guessable values** (deductibles, limits, waiting periods, copays).
- **Question = a customer question** answerable by ONE specific value buried in ONE leaf
  of the correct pack. The answer is that value — **extractive QA** (SQuAD-style: the
  answer is a span/value in the corpus), graded by **exact value match**.
- **Why it's defensible (answers the "you wrote the answer key" critique):** (1) values
  are arbitrary/non-round and company-specific (e.g. deductible **$437**, **23**-day
  wait) → no model has them memorized → without the right pack the model guesses a round
  number and is **confidently wrong**; (2) grading is objective extraction (the value is
  verbatim in exactly one corpus file) — we measure *did the agent navigate to the right
  needle*, which **is** the hypothesis, not our opinion; (3) **single source of truth**:
  one `POLICY_FACTS` object per pack renders the leaf tables AND defines the expected
  answer, so they cannot drift.
- **Why RAG still loses honestly:** the 49 distractor policies have structurally similar
  perils/clauses with *different* values → RAG retrieves a near-duplicate clause from the
  **wrong policy** → returns the wrong deductible. Colmena navigates SKILL.md (which
  policy?) → peril → sub-condition → exact value (3-level navigation RAG can't do).

**What this changes in the build:** the data model drops `CorePack.reference_fn`; packs
are built from `POLICY_FACTS`; `Question` becomes `(id, pack, leaf_path, field, text)`
with the expected answer derived from `POLICY_FACTS`; `score_skill_answer(question,
produced)` does exact value-match (no `df`, no tolerance) returning None for unparseable.
**Unchanged:** `Leaf`/`render_pack`/`_frontmatter`/`materialize_corpus`/
`corpus_token_estimate`/distractor packs/`rag_index`, the Colmena DAG + handler (T6), the
5 naive handlers (T7), the RAG arm (T8), and the driver (T9, minus the `df` arg to the
scorer). The metrics, arms, scale axis (5/20/50), and honesty stance below all stand —
only the *task content* and *grading* change from "compute a number" to "retrieve a value".

Sections §2–§6 below describe the superseded computation design; read them for the
metrics/arms/scale machinery (still valid), but the **domain, questions, and grading are
replaced by this §0**.

---

## 1. Hypothesis

> **Colmena loads only the relevant knowledge pack on-demand (`load_skill`), holding
> context tokens ~flat and accuracy high as the pack library grows; competitors must
> either stuff every pack into the prompt (token tax + lost-in-the-middle accuracy
> drop) or bolt on a RAG retriever (extra vector-DB / embeddings infra + retrieval
> misses → confidently-wrong answers). Colmena's nested reference tree lets the model
> *navigate* to a fact 3 levels deep, which flat RAG similarity-retrieval structurally
> cannot do.**

This is the **knowledge analogue of Demo #7** (lazy *tool* loading). Demo #7 proved
flat tokens as the *tool* count grows; Demo #9 proves the same as the *knowledge*
corpus grows — a hotter, more general claim (Anthropic Skills, Gemini CLI, etc.).

### Honesty stance (must survive a skeptical buyer)
- vs **naive all-in-prompt**: Colmena wins on **both** tokens and accuracy.
- vs **RAG**: Colmena **~ties on LLM context tokens** (both inject only what's needed)
  but wins on **infra-simplicity** (zero embeddings / vector store; one declarative
  field) and **miss-rate** (RAG mis-retrieval → wrong number). **We will NOT claim
  Colmena beats RAG on tokens** — that would be dishonest. The RAG arm is a genuine
  steelman, not a strawman.

---

## 2. Domain — Hybrid (data + business rules), the option chosen in brainstorm

A question bank over the existing **`orders_synthetic`** dataset (reused from Task 4 /
Demo #8). Each question is answerable **only** by applying one pack's
**non-default business rule** plus a **specific buried data fact**, and the answer is a
**number computed against the data** — so the answer key is arithmetic, not opinion.

### Why "non-default rule" is the accuracy lever
Every rule is **plausible-but-non-default**: without the pack the model computes a
*different, also-reasonable* number (e.g. it includes returns in net revenue, or omits
VAT). So skipping the pack yields a **confidently-wrong** answer, not merely a
rephrasing. That makes the accuracy gap clean and undeniable.

### Theme: a global e-commerce **financial-ops policy manual**, 50 sub-domain packs
Each pack is a domain a finance/ops analyst would really consult:
`revenue-recognition`, `returns-and-refunds`, `tax-by-region`, `shipping-cost-allocation`,
`discount-and-promo`, `payment-method-fees`, `fx-and-currency`, `channel-attribution`,
`cohort-definitions`, `chargebacks-and-fraud`, `cogs-and-margin`, `fiscal-calendar`, …
(50 total; ~6–8 are "core" packs the question bank targets, the remaining ~42 are
realistic distractors that inflate the library).

---

## 3. Pack structure — heavy, nested reference trees

A pack is **not** a one-liner. It is a Colmena skill with a **recursive reference tree**
(each file declares its own `references:` frontmatter; depth ≤ 5, ≤ 64 KB/file — within
Colmena's documented limits). Each leaf carries a **reference data table** — that is
what makes the pack information-dense *and* what the answer depends on.

```
tax-by-region/
  SKILL.md                    # overview + when-to-use; "for rates load `rates`; for exceptions load `edge-cases`"
  references/
    rates.md                  # frontmatter references: [eu, latam, apac]  (regional index + rounding rules)
    eu.md                     #   VAT table for 27 EU countries            (leaf)
    latam.md                  #   LATAM rate table                          (leaf)
    apac.md                   #   APAC rate table                           (leaf)
    edge-cases.md             # frontmatter references: [b2b, digital-goods]
    b2b.md                    #   reverse-charge rules                       (leaf)
    digital-goods.md          #   digital-VAT special rules                  (leaf)
```

To answer *"net revenue ex-VAT for shipped DE orders"* Colmena navigates **3 levels**:
`load_skill("tax-by-region")` → `load_skill(…, "rates")` → `load_skill(…, "rates/eu")` →
reads `DE = 19%`.

### Size budget (this is what makes "send everything" a bad strategy)
- **Per pack ≈ 15–30 KB** (overview + ~6 reference files with tables/prose).
- **Corpus of 50 ≈ 750 KB – 1.5 MB ≈ 200k–375k tokens.**
- **Naive all-in-prompt** pays ~200k–375k *input tokens on every question*. It
  technically fits gemini-2.5-flash's 1M window (so it "works"), but it is the giant
  cost bar, and accuracy drops as the needed fact drowns among 50 dense packs.
- **Colmena** pulls only the path it walks (`SKILL.md` + `rates.md` + `eu.md`) ≈ a few
  KB ≈ ~2–3k tokens. **~50–100× less.** The deeper the tree, the bigger the gap.
- **RAG** flattens the tree into chunks; the DE row sits in `eu.md` near 26 other EU
  rates and structurally-similar LATAM/APAC tables → real mis-retrieval risk; and it
  needs the embeddings + vector-store infra. RAG has **no notion of hierarchy** — it
  guesses by embedding distance where Colmena *navigates*.

### No-drift guarantee (defensibility)
Each pack is **generated from one structured data object** (rate tables + rule
constants). That single object **renders the whole markdown tree AND drives the Python
reference function** that produces the ground-truth number. They physically cannot
disagree → a skeptic cannot argue "your markdown says one thing, your answer key
another." The corpus is deterministic and regenerable from a seed.

---

## 4. The three arms (per framework)

| Arm | Mechanism | Expected outcome |
|---|---|---|
| **Colmena** (hero) | One `llm_call` with all M packs via `skills_path`; model calls `load_skill(pack[, ref])`, navigates the tree, answers | Flat low tokens; high accuracy; loads exactly the needed pack/leaf |
| **Naive all-in-prompt** | Concatenate all M packs' full markdown into the system prompt every question | Tokens explode with M; accuracy degrades at M=50 (lost-in-the-middle) |
| **RAG** | Embed all pack files, retrieve top-k chunks per question, inject only those | ~flat tokens (like Colmena) BUT vector-DB/embeddings infra + mis-retrieval → wrong number |

### Frameworks & idiomatic implementations (mirrors Demo #8's "idiomatic tool per framework")
- **Colmena** — native `skills_path` + `load_skill` (hero, only arm it runs).
- **5 competitors** (llamaindex, langchain, langgraph, crewai, google_adk) each run
  **both** `naive` and `rag`:
  - `naive` is mechanically identical everywhere (system-prompt stuffing) — included
    per-framework only for parity / proxy-token symmetry.
  - `rag` uses each framework's **idiomatic** retriever where it routes embeddings
    through the proxy cleanly: LlamaIndex `VectorStoreIndex`/`RetrieverQueryEngine`
    (the canonical RAG framework), LangChain `VectorStoreRetriever`. For frameworks
    whose native RAG cannot point embeddings at `OPENAI_BASE_URL` cleanly, fall back to
    a **shared minimal retriever** (`bench_common`: proxy embeddings + cosine top-k)
    and **label it as a fallback in the chart/docs** (honesty: no silent substitution).

> **Decision A (LOCKED 2026-06-21):** `naive` on **all 5** competitors; idiomatic `rag`
> on **LlamaIndex + LangChain** only (the two with first-class native retrievers that
> route embeddings through the proxy cleanly; LlamaIndex is the strongest steelman).
> The other three frameworks run `naive` only. Rationale: keeps the RAG plumbing
> focused on where it's idiomatic, avoids hand-rolled RAG that a skeptic could call
> unfair, and still gives a genuine steelman.

---

## 5. Question bank & controlled variable

- **Fixed question bank** (~15–20 questions) targeting the ~6–8 **core** packs. Several
  questions hit different leaves of the *same* pack's tree (exercises nested-reference
  navigation, e.g. DE vs BR vs JP rate → `rates/eu` vs `rates/latam` vs `rates/apac`).
- **Scale = library size M ∈ {5, 20, 50}** = the controlled variable. The core packs
  (and thus every needed fact) are **always present**; M grows by adding **distractor
  packs**. Difficulty = finding the right fact among M packs, *not* changing the
  questions. At M=5 there are ~0 distractors (the honesty anchor — everyone does fine);
  at M=50 there are ~42 distractors (where naive's prompt explodes and RAG mis-retrieves).
- Each question's expected answer is a **number** (or a tiny JSON object) produced by
  the pack's reference function.

---

## 6. Metrics & charts

Provider-authoritative tokens via the **LiteLLM proxy spans** (same as every prior
demo). Colmena cannot send `x-bench-run-id`, so its tokens are measured by the
**session-file line-delta** → **serial sweep, single managed proxy** (exactly the
Demo #7 protocol).

1. **Tokens vs pack-count (5/20/50)** — line per arm. Hero visual: `colmena` and `rag`
   low/flat; `naive` explodes. (mean LLM input+output tokens per question)
2. **Accuracy vs pack-count** — % correct number (reference function, tolerance). Hero:
   `colmena` high+flat; `naive` degrades at 50; `rag` below colmena (miss-rate).
3. **Selection / retrieval correctness** — `colmena` "loaded the correct pack" rate
   (from the `skills_used` summary field — Colmena observability) vs `rag` "retrieved
   the correct chunk" hit-rate. Explains *why* RAG misses.
4. **Cost-at-scale bar (M=50)** — $ per question per arm (tokens × pricing snapshot),
   à la Demo #7's `tokens_at_200_bar`. The single most quotable number.
5. **Capability / infra matrix** — native-declarative vs vector-DB-required vs
   prompt-stuffing; **tree-navigation: yes (colmena) / no (rag)**; lines-of-wiring.

### Token-accounting decision (RAG embeddings)
The **headline token metric counts only LLM completion-call tokens** (input+output) —
apples-to-apples across all arms, measured by proxy spans. **Embedding tokens are
reported separately** as an "infra cost" note (cheap per-token, but they represent an
*extra subsystem* RAG requires). Rationale: mixing embedding tokens into the headline
bar would muddy the context-tax comparison; surfacing them separately is the honest way
to credit RAG's real-but-different cost.

> **Decision B (LOCKED 2026-06-21):** route RAG embeddings **through the LiteLLM proxy**
> so embedding tokens are measured (reported separately from the headline LLM-token
> bar). If a framework cannot point its embeddings at `OPENAI_BASE_URL`, fall back to a
> size-based estimate with a noted caveat. (Both RAG arms — LlamaIndex, LangChain —
> support a configurable embeddings base URL, so the proxy path is expected to hold.)
> In practice the LiteLLM proxy's `/embeddings` route returned "No connected db" (a
> litellm limitation: embeddings require a DB even for a configured model, while chat
> completions do not), so RAG embeddings run direct-to-OpenAI and embed tokens are
> ESTIMATED from chunk size (chars/4) — the headline completion-token metric remains
> proxy-authoritative; embeddings are a secondary infra-cost figure.

---

## 7. Run plan & infra reuse

- **Serial sweep, single managed proxy** (Colmena delta requirement). Modes/arms ×
  pack-counts × frameworks × seeds, run one at a time under one long-lived proxy.
- **Seeds:** start at **3** (cost-aware — `naive@50` is the cost driver at ~200k–375k
  input tokens/question; flash pricing keeps total in the low tens of dollars). Seed
  controls which distractor packs pad the library and their order.

### Reused infrastructure
- `runners/_bench_common/bench_common/scenario_skills.py` (**new**): generate the pack
  corpus (one structured object/pack → renders the nested markdown tree on disk **and**
  exposes the reference function), the question bank, and the numeric scorer. Reuses
  `orders_synthetic` + Task 4's numeric-answer grading (`task04_scorer`).
- `runners/colmena/runner/dags/skills_agent.json` (**new**): `llm_call` with
  `skills_path` → generated corpus dir; system message instructing tree navigation.
- `runners/colmena/runner/tasks/task09_skills.py` (**new**): handler; reads
  `BENCH_SKILLS_DIR`, `BENCH_PACK_COUNT`; token-delta on the session file (Demo #7 pattern).
- `runners/<fw>/runner/tasks/task09_skills.py` (**new** ×5): `naive` + `rag` arms.
- `harness/orchestrator/demo_skills_run.py` (**new**): driver (mirrors
  `demo_codeexec_run.py` / `demo_tools_session_run.py`) — `--frameworks`, `--arms`,
  `--pack-counts`, `--seeds`; proxy-span token accounting; Colmena session-delta.
- `harness/tasks/09_skills.yaml`, `scripts/run_demo09.sh` (**new**).
- `harness/orchestrator/demo09_plots.py` (**new**): the 5 charts above.
- `docs/demos/demo09-skills.md` + `docs/demos/demo09-replication.md` (**new**).
- `scripts/setup_all.sh` (**modify**): add embeddings/vector deps to the competitor
  venvs that run the RAG arm (e.g. `llama-index`, `langchain` vector stores; an
  in-memory store — no external DB needed).

### Grading
A produced answer scores **correct** iff `|produced − reference| ≤ tolerance` (numeric,
2% tolerance, the Demo #8 `score_mutation` pattern). Empty / unparseable → **not
measured** (None), never silently 0 (the Demo #8 honesty fix).

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Packs not heavy enough → naive is cheap → demo collapses | Size budget enforced (≥15 KB/pack, corpus ≥200k tokens); nested trees; assert corpus token-count at generation time and fail if under target. |
| Skeptic: "you graded your own homework" | Single-source-of-truth: one data object renders both the markdown tree and the reference function → cannot drift; answers are arithmetic over real data. |
| Skeptic: "naive is a strawman, we'd use RAG" | RAG arm is a real steelman (idiomatic LlamaIndex/LangChain). We concede RAG ties on tokens; win is infra + miss-rate + tree-navigation. |
| RAG miss-rate artificially high/low (chunking choice) | Use each framework's *default* idiomatic chunker/retriever; document chunk size & k; do not hand-tune to make RAG look bad. |
| Cost blowup from naive@50 across seeds | 3 seeds, ~15 questions, flash model; cost-estimate gate in the driver before the full sweep. |
| Embeddings won't route through proxy for some fw | Documented fallback to shared cosine retriever + estimated embedding cost, labeled as fallback (no silent substitution). |
| Colmena 50-skill/node ceiling | M=50 is exactly the documented max — intentional; we hit the ceiling as a feature, not a bug. |

---

## 9. Out of scope (YAGNI)
- Multi-turn conversation memory (covered by Demo #5 / #7).
- Skill *authoring* DX comparison beyond the infra matrix row.
- Built-in skills (`skills.builtin`) — we use generated `skills_path` packs only.
- Hostile-skill / prompt-injection trust model (interesting, but a separate security demo).

---

## 10. Success criteria
1. Tokens-vs-M chart shows `naive` exploding while `colmena`/`rag` stay flat.
2. Accuracy-vs-M chart shows `colmena` high+flat, `naive` degrading at 50, `rag` below
   colmena due to miss-rate.
3. Selection/retrieval chart explains the accuracy gap (colmena loads right pack; RAG
   mis-retrieves at 50).
4. Every number reproducible from a seed via `scripts/run_demo09.sh`.
5. Docs state the honest RAG caveat (ties on tokens) prominently.
