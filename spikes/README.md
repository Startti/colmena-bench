# Framework integration spikes

Feasibility spikes for adding three new frameworks to the benchmark. Each spike
proves the **three make-or-break requirements** a framework must meet to become a
runner, without building the full task suite yet:

1. Point the model client at the LiteLLM proxy's OpenAI-compatible `base_url` + master key.
2. Inject the `x-bench-run-id` request header on **every** LLM call, so the proxy
   buckets provider-authoritative token spans into `proxy/spans/run-<id>.jsonl`
   (this is how the benchmark meters tokens — self-reports are never trusted).
3. Drive a multi-turn conversation with a tool call.

Model: `gemini-2.5-flash` via the proxy. Success criterion: the proxy writes a
per-run span file with non-zero `tokens_input`/`tokens_output` and `ok=true`.

## Results — all three PASS ✅

| Framework | Lang | Package (version) | base_url | `x-bench-run-id` header | Multi-turn + tool | Proxy metered |
|---|---|---|---|---|---|---|
| **Pydantic AI** | Python | `pydantic-ai-slim[openai]` (v2) | ✅ `OpenAIProvider(openai_client=...)` | ✅ `AsyncOpenAI(default_headers=...)` | ✅ 42 → 142 | ✅ 4 calls, in=496 out=184 |
| **OpenAI Agents SDK** | Python | `openai-agents` (0.x) | ✅ `set_default_openai_client` + `set_default_openai_api("chat_completions")` | ✅ `AsyncOpenAI(default_headers=...)` | ✅ 42 → 142 | ✅ 4 calls, in=496 out=184 |
| **Mastra** | TypeScript | `@mastra/core` 1.49 + `@ai-sdk/openai-compatible` 3.0 | ✅ `createOpenAICompatible({ baseURL })` | ✅ `createOpenAICompatible({ headers })` | ✅ 42 → 142 | ✅ 4 calls, in=420 out=180 |

**Verdict: all three are addable.** The `x-bench-run-id` header — the real risk,
since it must survive the framework's client abstraction — works in every case
because all three expose the underlying OpenAI-compatible client's default headers.

## Per-framework integration notes (for building the real runners)

### Pydantic AI (cleanest)
- `OpenAIChatModel("gemini-2.5-flash", provider=OpenAIProvider(openai_client=AsyncOpenAI(base_url, api_key, default_headers)))`.
- Tools via `@agent.tool_plain`; multi-turn via `agent.run(..., message_history=prev.all_messages())`.
- Stable v2, SemVer — lowest churn risk.

### OpenAI Agents SDK
- Must call `set_default_openai_api("chat_completions")` — the default Responses API is OpenAI-only and won't work against the proxy.
- Must call `set_tracing_disabled(True)` — the tracing exporter otherwise tries to reach OpenAI directly.
- Tools via `@function_tool`; multi-turn via `Runner.run(agent, prev.to_input_list() + [{...}])`.
- 0.x — watch for breaking changes between minors; pin exactly.

### Mastra (TypeScript)
- `createOpenAICompatible({ name, baseURL: base+'/v1', apiKey, headers: { 'x-bench-run-id': id } })`, then `provider('gemini-2.5-flash')`.
- **Tool `execute` signature in 1.49 is `async (inputData) => ...`** — `inputData` IS the validated input (the older `{ context }` destructure is wrong and silently fails the tool).
- Agent runs the tool loop automatically; multi-turn via `agent.generate([{role,content},...])`.
- The harness is Python — a Mastra runner needs a thin Node subprocess the orchestrator shells out to (same pattern as any non-Python runner).

## Daytona sandbox spike (for the demo08 CrewAI code-exec arm)

`spikes/daytona/spike.py` — separate spike proving the demo08 CrewAI arm can migrate off
its vendored Docker tool to Daytona (`DaytonaPythonTool` is a real `crewai_tools` 1.14.7 tool;
CrewAI removed its first-party `CodeInterpreterTool` in 1.14.0 for CVE VU#221883). PASSED:

- **Auth + sandbox:** `DAYTONA_API_KEY` (in `.env`, quoted — strip quotes) authenticates; a
  remote sandbox spins up. `pip install daytona` in `runners/crewai/.venv`.
- **Pandas runs:** `df.groupby(...).sum()` → `{'AR': 40, 'BR': 20}`.
- **Canary CONTAINED:** reading a host path from inside the remote sandbox → `FileNotFoundError`
  (the sandbox is a separate cloud machine with no host filesystem) → the "Contained" outcome.
- **CSV delivery:** the remote sandbox has no host mount, so the runner must **upload the CSV via
  the Daytona filesystem API** (`sandbox.fs`) rather than inlining a giant string literal — this
  also fixes the current inline-CSV `M=0.15` accuracy handicap.

Free tier: Daytona gives $200 credits, no credit card. demo08's ~36 short pandas runs cost cents.

## Reproduce

```bash
# from repo root, with .env populated
set -a; source .env; set +a
export LITELLM_PROXY_API_KEY="$LITELLM_MASTER_KEY"
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=spike ./proxy/start_proxy.sh &   # wait for :4000/health/liveliness

RID="spike-$(date +%s)"
SPIKE_RUN_ID="$RID" spikes/pydantic_ai/.venv/bin/python spikes/pydantic_ai/spike.py
SPIKE_RUN_ID="$RID" spikes/openai_agents/.venv/bin/python spikes/openai_agents/spike.py
SPIKE_RUN_ID="$RID" node spikes/mastra/spike.mjs
# then inspect proxy/spans/run-$RID.jsonl
```
