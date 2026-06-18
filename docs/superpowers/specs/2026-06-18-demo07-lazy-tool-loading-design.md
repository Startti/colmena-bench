# Demo #7 — Lazy tool loading: many tools without failing

**Status:** design approved 2026-06-18 · **Owner:** daniel@startti.co
**Type:** measured experiment (token + accuracy + reliability asymptote vs tool count)
**Bench task id:** `07_tools`

---

## 1. Goal & hypothesis

As you give an LLM agent more tools, the cost grows and quality degrades. Colmena's
**lazy tool loading** sends the model a light catalog (`name + summary`) and reveals
a tool's full schema only when the model asks for it via the synthetic `describe_tool`.
The hypothesis: with lazy loading you can add many more tools **(1)** without the call
failing, **(2)** without paying tokens for every schema, and **(3)** without the model
losing accuracy in picking/filling the right tool.

We measure three failure modes as a function of **tool count** (the "tool asymptote"):
- **accuracy** — does the agent select the correct tool and fill its args correctly?
- **tokens** — provider-authoritative input tokens per run.
- **hard error** — does the provider reject the request (4xx) at high tool counts?

Mechanism reference: `colmena/docs/developer_guide/29_lazy_tool_loading.md` —
`lazy_tool_loading: true` on an `llm_call`; per-tool `summary`/`eager`; the engine
rebuilds `tools[]` each turn as `[eager] + [describe_tool] + [discovered full schemas]`.

---

## 2. Experiment matrix

- **Configs (7):** colmena lazy-ON, colmena lazy-OFF (internal control: isolates that
  the feature — not Colmena in general — is the cause), crewai, langchain, langgraph,
  llamaindex, google_adk (the 5 always send full schemas; no lazy equivalent).
- **Tool count sweep:** 5, 10, 25, 50, 100, 200.
- **Needle difficulty (by param count):** easy (1-2 params), medium (3-5), hard (6-10).
- **Trials:** N=5 per cell, needle at a random index, distinct question per trial.
- Total ≈ 7 × 6 × 3 × 5 = **630 runs** (background batch; 200-tool cells are slow).
- **Model:** `gemini-2.5-flash`, temp 0, through the proxy (consistent with other demos).

---

## 3. Tool-set generator (the shared, fair substrate)

`runners/_bench_common/bench_common/scenario_tools.py`.

`generate_toolset(n, needle_difficulty, seed) -> dict` returns a framework-agnostic
spec used IDENTICALLY by all 7 configs for a given (n, difficulty, trial):

```jsonc
{
  "n_tools": 50, "needle_difficulty": "hard", "seed": 3,
  "question": "What is the total amount in USD of order ORD-7?",
  "needle": "get_order_total",
  "expected_args": {"order_id": "ORD-7"},
  "expected_answer": "4242.00",
  "tools": [
    {"name": "get_order_total", "summary": "...", "description": "...",
     "params": [{"name": "order_id", "type": "string", "required": true, "description": "..."}],
     "is_needle": true, "answer": "4242.00"},
    {"name": "list_shipments", "summary": "...", "params": [...], "is_needle": false},
    ...
  ]
}
```

- **Difficulty tiers by param count:** easy 1-2, medium 3-5, hard 6-10; param types vary
  (string/int/enum/bool/array; some required). The **population is always a ~⅓/⅓/⅓ mix**
  of tiers so the total schema payload is realistic (hard tools have large schemas → more
  tokens + more attention competition).
- **Distinguishable summaries:** generated from domain templates (verb × noun × domain:
  get/list/update/create × orders/customers/shipments/invoices/tickets/... ) so the
  catalog is genuinely usable by lazy loading and the names don't collide.
- **The needle** is one tool whose difficulty = `needle_difficulty`, with a deterministic
  answer (e.g. `get_order_total(order_id="ORD-7") → "4242.00"`). Distractors are no-ops
  returning `"not applicable"`. The question targets ONLY the needle.
- **Needle at a random index** (seeded) to avoid position bias.
- **Tool-call logging:** every tool (needle + distractors) appends `{tool, args}` to a
  per-run JSONL (`BENCH_TOOLCALL_LOG`), so the driver knows exactly which tool was called
  with which args — independent of the final text.
- **Scoring helpers:** `score(spec, toolcall_log, final_answer) -> {selection_ok,
  arg_ok, answer_ok}`.

---

## 4. Per-framework handlers

`runners/<fw>/runner/tasks/task07_tools.py`. Each reads the spec path from env
`BENCH_TOOLSET_PATH`, builds the N tools in its idiom, runs the agent on `spec.question`,
returns `(answer, usage, extras)`. Each tool's function logs its call to
`BENCH_TOOLCALL_LOG` then returns its answer (needle) or `"not applicable"` (distractor).

- **Colmena:** a DAG with one `llm_call` node whose `tool_configurations` holds the N
  tools (needle = `python_script` returning the answer; distractors = `python_script`
  no-op). Each tool config carries a `summary`. The node's `lazy_tool_loading` is set
  from env `BENCH_COLMENA_LAZY` (`1`→true, `0`→false) — same handler drives both the
  ON and OFF configs. Mirrors `task04_expert.py` env setup.
- **CrewAI / LangChain / LangGraph / LlamaIndex / Google ADK:** register the N tools via
  the framework's native tool API (mirroring each runner's `task04_expert.py` /
  `task06_refund.py` tool wiring) and run one agent turn. They always send full schemas.

Handler contract: `run(task_def, llm, args)`; `args.variant` carries the tool-count label
(e.g. `n50`). Difficulty, count, lazy and the toolset all arrive via the spec file + env.

---

## 5. Driver, metrics, outputs

`harness/orchestrator/demo_tools_run.py` — nested sweep config × count × difficulty × trial.
Per cell:
1. `generate_toolset(count, difficulty, seed=trial)` → write spec JSON to a temp path;
   set `BENCH_TOOLSET_PATH`, `BENCH_TOOLCALL_LOG`, and (colmena) `BENCH_COLMENA_LAZY`.
2. Run the framework handler in one process (unique run-id → its own proxy spans +
   toolcall log). Capture final answer, exit status / exception, 4xx from proxy.
3. Score: `selection_ok`, `arg_ok`, `answer_ok` (from the toolcall log + answer);
   `tokens_in` = sum of this run's proxy spans (ALL round-trips — lazy pays for its
   `describe_tool` calls honestly); `hard_error` = run errored / provider 4xx.

Aggregate mean±std per (config, count, difficulty) → `runs/demo07/summary.{json,csv}`
so charts/analysis never re-run the sweep.

**Metrics reported:** selection accuracy, arg accuracy, answer accuracy, mean input
tokens, hard-error rate.

---

## 6. Charts

`harness/orchestrator/demo07_plots.py`, faceted by needle difficulty:
- **accuracy vs #tools** (7 lines) — expect colmena-lazy-ON flat/high; others decline,
  worse at higher difficulty.
- **tokens vs #tools** (log scale) — colmena-lazy-ON ~flat; lazy-OFF + competitors grow
  ~linearly with tool count.
- **hard-error rate vs #tools**.
- **bars at 200 tools** — tokens and accuracy per config (the punchline slide).
Colmena highlighted green; lazy-OFF as the internal control alongside the competitors.

---

## 7. File layout

- `runners/_bench_common/bench_common/scenario_tools.py` — generator + tiers + scoring + toolcall log
- `harness/tasks/07_tools.yaml` — task def (id `07_tools`)
- `runners/{colmena,crewai,langchain,langgraph,llamaindex,google_adk}/runner/tasks/task07_tools.py` — 7 handlers
- each runner's `runner/__main__.py` — register `07_tools`
- `harness/orchestrator/demo_tools_run.py` — sweep driver
- `harness/orchestrator/demo07_plots.py` — charts
- `scripts/run_demo07.sh` — owns the proxy + runs the sweep (one command)
- `docs/demos/demo07-many-tools.md` + `demo07-replication.md`

---

## 8. Fairness rules

- The SAME generated toolset (byte-identical spec file) is fed to all 7 configs for each
  (count, difficulty, trial). Same model, temp, proxy.
- Lazy's token count includes every round-trip (catalog + each `describe_tool` + final
  call) — no undercount.
- colmena lazy-OFF is the internal control: it must use the identical DAG/handler, only
  the `lazy_tool_loading` flag differs.
- Each competitor uses its framework's native/idiomatic tool registration.

---

## 9. Risks / open items

- **Hard-error may not fire on gemini.** Whether a provider rejects N tools depends on its
  limits; gemini-2.5-flash may accept 200 tools. If the hard-error curve is empty, report
  it honestly and let accuracy+tokens carry the result. Optional: cross-check one high-count
  cell on another provider (claude-haiku / gpt-4o-mini via the proxy) to see if a cap appears.
- **Summary distinguishability at 200.** The generator must produce 200 non-colliding,
  meaningful summaries or lazy's catalog degrades unfairly; the domain-template generator
  handles this — verify at n=200 during build (first verifiable step).
- **Competitor client-side limits.** Some frameworks may choke building 200 tools before
  the provider call; that's itself a finding — record it as a hard_error for that cell.
- **Cost/time.** ~630 runs; run as a background batch via `run_demo07.sh`. Lazy cells do
  multiple round-trips (slower per run but fewer tokens).

---

## 10. Out of scope
- Tuning `eager` tools (always-on tools) — fixed off for all lazy runs.
- Multi-tool / sequential-tool tasks (this is single-needle by design).
- Non-gemini models as the primary axis (gemini is primary; other providers only an
  optional hard-error cross-check).
