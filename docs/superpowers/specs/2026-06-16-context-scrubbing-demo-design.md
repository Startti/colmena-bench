# Hero Demo #1 — "The Context Tax" (multi-turn token asymptote + LOC)

**Date:** 2026-06-16
**Status:** design approved (ready for implementation plan)
**Supersedes the CSV asymptote as hero; see** `2026-06-11-benchmark-strategy-colmena-differentiators.md`

## Goal

Sell Colmena by measuring two of its genuine, code-verified differentiators in a
single fair, multi-turn benchmark across all 6 frameworks (Colmena + CrewAI,
LangChain, LangGraph, LlamaIndex, Google ADK):

1. **Attachment management** — `load_attachment` reads a document ephemerally,
   only when needed, never persisting its content to history.
2. **Always-on tool-result scrubbing** — binary/oversize tool outputs are elided
   before they ever reach the LLM context.

The headline: **cumulative input tokens (and USD) per turn diverge** — Colmena
stays flat, the 5 Python frameworks grow super-linearly. Plus **lines of code** to
stand up the agent (node-vs-code).

## The two mechanisms (code evidence)

### A. Attachment / `load_attachment` (ephemeral, catalog-driven)
- A doc attached via `files[]` is NOT injected into context; the model sees a
  ~30-token catalog line and calls `load_attachment(document_id)` to read it.
- Content is injected **for that turn only** and persisted as a short marker, not
  the content (`docs/developer_guide/31_load_attachment.md`, Plan B / D7).
- **Honest because** the model still reads the doc whenever a question needs it →
  answer quality preserved. The win is: (a) doc-irrelevant turns pay 0 for the
  doc, and (b) the doc never accumulates in history.
- Competitors (idiomatic default): the doc text sits in the first message and is
  re-sent in full every turn → paid N times.

### B. Always-on binary/oversize tool-result scrubber
- `scrub_value_for_llm` (`dag_tool_executor.rs:1853`), applied in `execute`
  (`:1921`) BEFORE the result reaches the LLM:
  - `data:<mime>;base64,...` → `[binary elided: mime=…, encoded_size=N bytes]`,
    **always**, any size ("binary base64 in the LLM context is always a footgun").
  - strings > `max_tool_result_bytes` (default `DEFAULT_MAX_TOOL_RESULT_STRING_BYTES
    = 50KB`) → `[truncated: original_size=N bytes …]`.
- **Honest because** we demo this with BINARY (base64) tool outputs, which are
  genuinely useless in an LLM context (the code says so) — not with useful large
  text (which Colmena would scrub pre-LLM, hurting its own answers). Scrubbing
  happens pre-LLM, so the demo tool must return content the model never needs to
  read verbatim: a generated chart image.
- Competitors (idiomatic default): the base64 tool result becomes a function/tool
  message and is retained in history forever → accumulates every subsequent turn.

## Scenario — a "report assistant", 10 fixed turns

One reference report (synthetic, ~12–15 "pages" of plain text/markdown, fixed
content) attached once. A deterministic tool `generate_chart(description)` that
returns a FIXED base64 PNG (~20–40KB, same blob regardless of input — removes
variance). The same 10 user messages, in the same order, for all 6 frameworks:

| # | User message | Type | Exercises |
|---|---|---|---|
| 1 | Summarize the report's key findings. | doc | A |
| 2 | Which region had the highest revenue? | doc | A |
| 3 | Generate a bar chart of revenue by region. | chart | B |
| 4 | What was the growth rate vs last quarter? | doc | A |
| 5 | Based on that, is the trend positive? | follow-up | — |
| 6 | Generate a line chart of the monthly trend. | chart | B |
| 7 | Summarize what the two charts show. | follow-up | — |
| 8 | What were the top 3 risks in the report? | doc | A |
| 9 | Generate a chart of risk severity. | chart | B |
| 10 | Give an executive summary of this whole conversation. | follow-up | — |

Mix: 4 doc-reads, 3 chart/binary calls, 3 pure follow-ups. Colmena reads the doc
only on the 4 doc turns (ephemeral) and elides all 3 base64 charts; competitors
carry the doc on all 10 turns and accumulate 3 base64 blobs.

## Metrics

1. **Cumulative input tokens per turn** (provider-authoritative, from proxy
   spans) — the asymptote chart. PRIMARY headline.
2. **Total USD** and **total tokens** per framework (from the pricing table).
3. **Turn-10 input tokens** — "the context tax" at the end of the conversation.
4. **Lines of code (LOC)** to stand up this agent per framework — node-vs-code.
   See methodology below.
5. **Quality guardrail (light)** — a lightweight check that 2–3 doc-question
   answers are reasonable (keyword/number presence), to prove Colmena does not
   "win" by losing answer quality. Not hard-scored for the MVP.

### Per-turn token attribution (framework-agnostic)
Colmena's OpenAI adapter cannot forward custom HTTP headers, so we do NOT rely on
a per-turn header. Instead each runner emits the **wall-clock timestamp at every
turn boundary**; the orchestrator buckets proxy spans into turns by `ts_start`.
This works identically for all 6 frameworks. (Spans are already tagged per
`run_id` via `x-bench-run-id` for the 5 Python runners and `BENCH_RUN_ID` for
Colmena.)

### LOC methodology (fair + defensible)
- Count only the lines a developer writes to stand up THIS agent: the multi-turn
  conversation handling, the document/attachment wiring, the tool definition, and
  (for Colmena) the DAG JSON + its thin driver.
- EXCLUDE the shared bench harness/scaffolding that is identical for all
  frameworks (arg parsing, proxy plumbing, output emission via `bench_common`).
- Count both: **default LOC** (what we actually wrote for the default baseline)
  and a documented estimate of the **EXTRA LOC** each competitor would need to
  match Colmena's behavior (manual history trimming, attachment caching, base64
  scrubbing) — the honesty delta. Colmena's extra-LOC = 0 (built-in).
- Report a small table: framework · default LOC · est. extra LOC to match Colmena.
  Use a consistent counter (non-blank, non-comment lines via `cloc` or equivalent)
  and state it.

## Fairness controls + honesty notes

- Same model (`gemini-2.5-flash`) through the same LiteLLM proxy; tokens are
  provider-authoritative.
- Same fixed report text, same deterministic `generate_chart` (identical base64
  blob), same 10 user messages in the same order.
- Cap assistant `max_tokens` to bound response-length noise (the doc + base64
  dominate the asymptote, but we still cap to reduce per-framework variance).
- Competitors run their **idiomatic default** multi-turn memory (full history,
  retained tool outputs). The report states this explicitly and documents what
  you'd build in each to match Colmena (the LOC delta above). No strawman tuning,
  no hidden handicap.
- Colmena: doc via `files[]` + `load_attachment` + a tool node returning base64;
  the 5 Python frameworks put the same doc text in the first message + a function
  tool returning the same base64. Apples-to-apples content, idiomatic plumbing.

## Architecture / bench integration

- `runners/_bench_common/bench_common/scenario05.py` — shared assets: the fixed
  report text, the 10-turn script (list of user messages + per-turn type tag),
  and `generate_chart()` returning the fixed base64 PNG. All runners import these
  so the content is provably identical.
- `runners/<fw>/runner/tasks/task05.py` — per framework: a multi-turn loop using
  that framework's native conversation memory, the shared tool, and the shared
  doc; emits per-turn boundary timestamps + the final answers.
- `harness/tasks/05_context_scrubbing.yaml` — the conversational task definition
  (model, turn count, timeout, success kind).
- `harness/orchestrator/full_run.py` — bucket spans per turn by the runner's
  boundary timestamps; emit cumulative-tokens-per-turn series + the LOC table +
  the asymptote chart data.

## Out of scope (MVP)

- Tuned/optimized competitor baselines (we measure default + document the delta).
- Hard answer scoring (light guardrail only).
- The other hero demos (#2 masking, #3 HITL, #4 prod-agent-in-JSON) — separate
  spec → plan cycles.
- Chart rendering polish; the MVP emits the data series + a simple chart.

## Risks / things to validate during implementation

- Confirm each Python framework's default memory actually retains base64 tool
  results across turns (expected, but verify per framework — some may stringify
  or drop them).
- Confirm the base64 blob size lands the per-turn gap in a clearly visible range
  (≥ a few thousand tokens per retained blob).
- Confirm span→turn bucketing by timestamp is unambiguous (turns are sequential;
  no overlapping concurrent calls within a runner).
- Confirm Colmena's `load_attachment` works with a text/markdown doc (the docs
  show PDF/image; text should work via the same path — validate with a smoke).
