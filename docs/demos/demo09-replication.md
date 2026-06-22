# Demo #9 — Replication

## What it measures
Knowledge-navigation cost across a growing corpus of insurance policy packs ("Colmena
Seguros"), three arms (`colmena` `load_skill` / `naive` prompt-stuff / `rag` retrieval),
swept over **5 / 20 / 50 packs** × **18 customer questions** × **3 seeds**.
Metric of record: provider-authoritative **completion input tokens** from the LiteLLM
proxy spans; accuracy by **exact value match** against corpus-unique answers.

## Prerequisites
- `.env` with `GEMINI_API_KEY`, `OPENAI_API_KEY` (RAG embeddings go direct to OpenAI),
  `LITELLM_MASTER_KEY`, `LITELLM_PROXY_API_KEY`, `COLMENA_DATABASE_URL`.
- Per-framework venvs built: `bash scripts/setup_all.sh` (installs
  `llama-index-embeddings-openai` for the RAG arm; LangChain uses `InMemoryVectorStore`
  from `langchain-core`, no extra dep).
- Colmena PyO3 module built in `runners/colmena/.venv` (`maturin develop --release`).

## Run
```bash
bash scripts/run_demo09.sh --seeds 3 --yes
```
This: starts a managed LiteLLM proxy (`PROXY_BENCH_RUN_ID=demo09`), runs the **serial**
sweep (`harness/orchestrator/demo_skills_run.py`), writes
`runs/demo09/summary.{json,csv}`, and regenerates the 5 charts in `runs/demo09/plots/`.
**Serial is required**: Colmena cannot send the `x-bench-run-id` header, so its tokens are
measured by a line-count **delta** on the proxy session file `run-demo09.jsonl`; concurrent
cells would corrupt the delta.

Subsets: `--frameworks "colmena llamaindex"`, `--arms naive,rag`, `--pack-counts 5,20`,
`--questions <id,id>`, `--seeds N`, `--merge-baseline <summary.json>`. `--yes` skips the
cost gate (the sweep is ~60M input tokens, dominated by `naive@50`).

## How the corpus is built (single source of truth)
`bench_common.scenario_skills`:
- `policy_value(pack, peril, sub, field)` — deterministic, non-round, per-leaf-distinct
  value (SHA-256 over `pack|peril|sub|field`). Ranges widened so every targeted value is
  **unique across the entire 50-pack corpus at seeds 0/1/2** (guaranteed by
  `test_question_expected_values_unique_in_corpus_for_reported_seeds`) — a wrong retrieval
  always yields a wrong number.
- `materialize_corpus(dir, pack_count, seed)` — writes the 6 core packs + distractor
  policies (real policy structure, different names/values) to `dir`; same value object
  renders the leaf tables AND defines the expected answer (cannot drift). Density floor
  enforced: 50-pack corpus ≥ 150k tokens (actual ≈ 225k).
- Reference files are stored **FLAT** (`references/<name>.md`); the tree is logical, via
  frontmatter `references:` — this matches the Colmena engine
  (`filesystem_skill_repository.rs`).

## Token accounting
- **Completion tokens**: header-capable frameworks → `proxy/spans/run-<run_id>.jsonl`;
  Colmena → delta on `proxy/spans/run-demo09.jsonl`. Split from embedding spans by
  `model_alias`.
- **Embedding tokens**: RAG embeds **direct to OpenAI** (the proxy `/embeddings` route
  returns "No connected db" — a litellm limitation), so they don't appear in proxy spans;
  the driver **estimates** them as `embed_chars // 4` (reported separately, not in the
  headline token metric). The harness re-embeds per call, so embed figures overstate a
  cached production RAG.

## Scoring
`scenario_skills.score_skill_answer(question, produced)` — exact match of the
authoritative value (locale-robust integer extraction); returns `None` (not 0) for
empty/unparseable answers, which are excluded from accuracy means (honesty rule).

## Expected output
`runs/demo09/summary.{json,csv}` (1296 rows: framework, arm, pack_count, seed,
question_id, correct, llm_tokens_in/out, embed_tokens, retrieval_hit, skills_used_count,
embed_estimated, error) and `runs/demo09/plots/{tokens_vs_packs, accuracy_vs_packs,
retrieval_vs_navigation, cost_at_50_bar, capability_matrix}.png`.

## Known caveats (see demo09-skills.md)
- Win is **cost/tokens (21.5× vs naive at 50 packs)**, not accuracy (all arms ≈100% at
  20/50); vs RAG comparable on metrics, Colmena simpler on infra.
- M=5 has only 5 of 6 core packs (a targeted policy is absent) → that point is confounded.
- ~0.5% cells error on OpenAI embeddings 429 rate-limit (langchain rag@50); excluded.
