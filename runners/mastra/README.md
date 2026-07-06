# Mastra runner (TypeScript)

The TypeScript/[Mastra](https://mastra.ai) runner — a Node subprocess the Python
orchestrator shells out to. It proves colmena-bench is **framework- and
language-agnostic**: same CLI contract, same output JSON schema, same LiteLLM
proxy path as the six Python runners, but a different language and SDK. This is
the arm that answers the "is this just a Python benchmark?" objection.

## How it plugs in

- **Invocation.** `harness/orchestrator/full_run.py:runner_cmd()` returns
  `["node", "runner/index.mjs"]` for `mastra` (and `python -m runner` for the
  Python runners). Every driver calls `runner_cmd(fw)`, so the harness branches
  on language in exactly one place.
- **Proxy + spans.** `runner/llm.mjs` builds an OpenAI-compatible provider at the
  proxy's `/v1` route and sets the `x-bench-run-id` header on every request, so
  the proxy buckets this run's spans to `proxy/spans/run-<run_id>.jsonl` (mastra
  is in each driver's `HEADER_CAPABLE` set). Token accounting is done at the proxy.
- **Output.** `runner/core.mjs` emits the identical payload schema as
  `bench_common/core.py` (tokens, ram_peak_mb, cpu_*_s, success, host, extras…).

## Scenario fidelity

Deterministic scenario assets (the Q3 report, the 10-turn script, the ~32 KB
chart payload, the refund + secrets assets) come from `data/bench_fixtures.json`,
generated from the Python `bench_common` (the single source of truth) by
`scripts/export_ts_fixtures.py`. Reading the fixture guarantees the TS runner's
data is byte-identical to the Python runners' without hand-porting. Toolsets
(task07) arrive via `BENCH_TOOLSET_PATH` written by the driver, so no generator
is duplicated.

## Tasks (4/5)

| task | id | what it shows |
|---|---|---|
| Context tax | `05_context_scrubbing` | multi-turn memory re-sends the chart payload every turn (~21× input-token growth) |
| Refund (hardened) | `06_refund` | DIY two-phase HITL suspend/resume + critic-retry + hand-rolled outbound masking |
| Tools at scale | `07_tools` | dynamic tools from a spec; needle selection + args |
| Secrets (naive) | `10_secrets` | the naive competitor arm: secrets leak into the LLM context (Colmena's counterfactual) |

`08_codeexec` is intentionally **not** ported: its arm executes model-written
**pandas** over a DataFrame, which is Python-specific; a JS transliteration would
measure a different thing. The four above exercise every other benchmark
dimension end-to-end.

## Run it

```bash
cd runners/mastra && npm install
# then drive it like any framework, e.g.:
python harness/orchestrator/demo_secrets_run.py --frameworks mastra --variants collect,echo --seeds 1
```
