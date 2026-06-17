# Demo 05 — "The Context Tax" (multi-turn token asymptote)

**The hero demo.** A fixed 10-turn conversation, run live across all 6 frameworks
through the same proxy and model, measuring **cumulative input tokens per turn**.
Colmena stays comparatively flat; the five Python frameworks grow ~linearly with
conversation history.

- **Design spec:** [../superpowers/specs/2026-06-16-context-scrubbing-demo-design.md](../superpowers/specs/2026-06-16-context-scrubbing-demo-design.md)
- **Reproduce:** `./scripts/run_demo05.sh` → `runs/demo05/report/`
- **Run date:** 2026-06-16 · model `gemini-2.5-flash` · tokens provider-authoritative (proxy)

---

## 1. What it measures — two built-in Colmena behaviors

| Mechanism | Colmena | The 5 competitors (default) |
|---|---|---|
| **A. Document handling** | Ephemeral `load_attachment`: the report (~3,000 tok) is read only on the turns that need it and is **never pinned** into history | The report sits in the first message and is **re-sent in full every turn** |
| **B. Binary tool output** | Always-on scrubber elides `data:…;base64,…` and oversize tool results **before they reach the model** | The base64 chart (~8,000 tok each) is **retained in history** and re-sent every later turn |

Code evidence: scrubber `scrub_value_for_llm` / `scrub_tool_result_output` in
`dag_tool_executor.rs` (applied in `execute()` before the result reaches the LLM);
attachment catalog + ephemeral read in `docs/developer_guide/31_load_attachment.md`.

---

## 2. The scenario (identical for all six)

A "report analyst" assistant. One synthetic Q3-2026 report (~12,000 chars) is
attached once. A deterministic `generate_chart(description)` tool returns a
**fixed** base64 PNG (~32 KB). The same 10 user messages, same order, for everyone
(defined in `bench_common/scenario05.py`): 4 doc questions, 3 chart-generation
turns, 3 pure follow-ups.

---

## 3. Results — tokens, cost

(Representative single run; the Colmena total varies ~37k–66k across runs because
the model decides on each turn whether to re-read the doc via `load_attachment`,
while the competitors are stable ~385k–452k. The gap is consistently **≥6×**.)

**N=12 runs, mean ± std** (data: `runs/demo05/report/agg_n12_summary.csv`; charts:
`runs/demo05/report/plots/`).

| Framework | ver | total input tok (mean±std) | turn-10 tok | USD (10 turns) |
|---|---|--:|--:|--:|
| **colmena** | 0.4.0 | **37,619 ± 5,603** | **1,927** | **$0.0184** |
| langgraph | 1.2.4 | 404,095 ± 23,121 | 71,181 | $0.1255 |
| llamaindex | 0.14.22 | 419,934 ± 34,873 | 71,225 | $0.1306 |
| google_adk | 2.2.0 | 445,370 ± 11,614 | 71,395 | $0.1390 |
| langchain | 1.3.6 | 452,158 ± 456 | 71,144 | $0.1406 |
| crewai | 1.14.6 | 452,358 ± 285 | 71,202 | $0.1420 |

**Headline (Colmena vs competitor median ~448k / ~71.2k):**
- **~12×** fewer total input tokens (Colmena's wider ±std is the model choosing
  per turn whether to re-read the doc; competitors are near-deterministic)
- **~37×** lower at turn 10 alone — the gap widens with every turn
- **~7.6×** lower USD

Per-turn cumulative curve: see `plots/2_line_cumulative.png` (Colmena flat with a
±std band; the five competitors climb). Per-turn CSV: `agg_n12_per_turn.csv`.

---

## 4. Results — lines of code (node vs code)

LOC rules: exclude blanks, comments, docstrings, and prompt-string content
(identical across frameworks, shared via `bench_common`); **Colmena's agent is a
declarative DAG (JSON) — reported separately as config, not code**, because it has
no loops/conditionals (the same way a competitor's YAML or SQL schema isn't
application code). **Code LOC** = the imperative handler `.py` a developer writes
and maintains.

| Framework | Handler Code LOC |
|---|--:|
| **colmena** | **53** ← leanest |
| langgraph | 67 |
| langchain | 70 |
| google_adk | 83 |
| llamaindex | 97 |
| crewai | 124 |

Colmena agent = `demo05_turn.json`: **~71 declarative lines, 0 imperative code.**
The Colmena Python is a thin runner: load the DAG once, then feed each turn's
message via `inject_payload` (the engine resolves the prompt from the trigger
payload — no per-turn templating). The essential "run the DAG" core is ~7 lines.

### Reading

With the agent expressed as a declarative DAG (not Python), **the imperative code
you write and maintain for Colmena is the smallest of the six (53 LOC vs 67–124)**
— while *also* getting context scrubbing + ephemeral attachments that the others
don't have at any line count out of the box.

Be precise for a skeptic: if you instead count the 71-line DAG as "the agent
definition," it's comparable to a competitor's agent-construction code — so the
honest, two-part claim is: **(1) the code you maintain is smaller, and (2) to
match Colmena's token behavior the competitors would need extra hand-written
infrastructure** (history trimming, attachment caching, base64 elision).

This gap **widens with agent complexity**: a simple chat is where competitors are
leanest (ready primitives like `create_react_agent`+`MemorySaver`). Add production
hardening — HITL + retries + a critic loop + secret masking — and Colmena stays
declarative JSON while competitor glue grows into the hundreds of lines. That
amplified node-vs-code comparison is **Demo #4**. For Demo 05, both the token
asymptote (≥6×) **and** the leaner maintained-code count hold.

---

## 4b. Resources — RAM, CPU, latency (N=12, honest)

Measured per runner process (the shared proxy/provider are excluded; for Colmena
the in-process Rust engine IS included). Peak RSS is sampled during the run (true
peak, not an end snapshot); CPU is `getrusage` user+sys.

| Framework | Peak RAM (MB) | CPU (s) | LLM calls | provider latency |
|---|--:|--:|--:|--:|
| **colmena** | **49 ± 3** | 0.80 ± 0.11 | 18.8 | lowest |
| langchain | 96 | 0.54 | 13 | |
| langgraph | 107 | 0.60 | 13 | |
| llamaindex | 174 | 1.06 | 13 | |
| google_adk | 250 | 1.39 | 13 | |
| crewai | 279 ± 1 | 1.48 | 13 | |

- **RAM → clear Colmena win:** 49 MB vs 96–279 MB (2–6× less). The Rust core has a
  far smaller footprint than the heavy Python agent frameworks. (`plots/11_bar_ram.png`)
- **CPU → honest tie/mid:** Colmena 0.80 s sits *mid-pack* — langchain (0.54) and
  langgraph (0.60) use less, because Colmena rebuilds its engine (tokio + Postgres
  pool) on each `run_dag` call. Not a Colmena win. (`plots/12_bar_cpu.png`)
- **LLM calls:** Colmena makes ~19 vs 13 — the extra `load_attachment` round-trips,
  which count *against* it in tokens/latency and it still wins on tokens.
- **Wall-clock latency (NOT shown as a win):** Colmena's end-to-end wall time is
  high in this bench because the handler calls `run_dag` once per turn and the
  engine is rebuilt each call. That is a **bench-harness artifact** — a production
  deployment keeps the engine warm (`serve_dag`/persistent session). We disclose it
  and do not feature it; the **provider-side** latency (actual model time) is the
  lowest of the six.

## 5. Fairness controls

- Same model, same proxy, same fixed 10-turn script, same report + chart payload
  for all six. Tokens are provider-authoritative (captured at the proxy).
- Competitors use their own **default idiomatic** memory — no hand-tuning.
- Colmena's per-turn `load_attachment` round-trips (extra LLM calls) **are
  counted against it**.
- USD is input-dominated (output small, uncapped at temperature 0).

### Anticipated objections (from adversarial review) + rebuttals

- *"You forced competitors to hoard base64 they'd never keep."* — That **is** the
  default. None of the 5 scrub binary/oversize tool results out of the box;
  retaining the tool message is standard memory behavior. Matching Colmena
  requires hand-written elision. The ~32 KB chart is representative of a real
  chart PNG (20–100 KB), not a worst case.
- *"Colmena under-counts its tokens."* — Verified false: all 25 Colmena spans
  (including `load_attachment` round-trips) are bucketed and summed.
- *"Colmena wins by losing answer quality."* — Verified false: its doc-turn
  answers are correct (turn 1 "North America", turn 7 "Supply chain", turn 0
  "positive trend"); only the 3 chart turns return short confirmations by design.

Adversarial verdict: **the headline is sound and fair.**

---

## 6. Known caveats (disclosed)

- **LlamaIndex** returned empty text on turns 3–4 (an agent quirk; exited 0, no
  crash). It does not affect tokens and LlamaIndex still ranks far above Colmena.
- The Colmena smoke `scripts/smoke_demo05_colmena.sh` uses a **fixed** session id,
  so a re-run can show a stale "attachment expired" (old Postgres row + cleaned
  storage). The real run (`run_demo05.sh`) and the orchestrator use unique
  sessions and pass cleanly with real doc answers.

---

## 7. Reproduce

```bash
./scripts/run_demo05.sh        # proxy up → 6 runners → report
cat runs/demo05/report/report.md
cat runs/demo05/report/quality_check.md
```
Requires the Colmena binding built from `develop` (includes engine fixes
#103/#104) and `.env` with `COLMENA_DATABASE_URL` + `SECURE_VALUES_KEY`.
