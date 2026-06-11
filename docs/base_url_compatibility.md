# base_url override compatibility matrix

> **T04 deliverable.** Documents how each of the 6 framework runners routes
> LLM calls through the LiteLLM proxy (`LITELLM_PROXY_BASE_URL`). The proxy
> is the source of truth for token / cost metrics (see METHODOLOGY §4), so
> every LLM call **must** flow through it.
>
> **Status legend** (column "Verified"):
> - ✅ — verified by a hello-LLM call captured in `proxy/spans/`
> - 🟡 — config believed correct; verification gated on API keys
> - ❌ — known broken; escalation needed
>
> Verification runs are gated on the API keys landing in `.env`. Until then
> the matrix tracks the *intended* override path per framework.

## Matrix

| # | Framework | Override mechanism | Where to set | Verified |
|---|---|---|---|---|
| 1 | **Colmena** | `OPENAI_BASE_URL` env + drive via `provider=openai`, `model=gemini-2.5-flash` (after the base_url patch) | env / `runners/colmena` | ✅ (2026-06-11, smoke) |
| 2 | **CrewAI** | `LLM(model="openai/<alias>", base_url=...)` — the `openai/` prefix is **required** (see finding) | `runners/crewai/runner/llm.py` | ✅ (2026-06-10, N=3) |
| 3 | **LangChain** | `ChatOpenAI(base_url=...)` for OpenAI-style models, or `ChatLiteLLM` wrapper | `runners/langchain/tasks/task*.py` | 🟡 |
| 4 | **LangGraph** | Same as LangChain (LangGraph uses LangChain model wrappers) | `runners/langgraph/tasks/task*.py` | 🟡 |
| 5 | **Google ADK** | `LiteLlm(model=..., api_base=...)` wrapper from `google.adk.models.lite_llm` | `runners/google_adk/tasks/task*.py` | 🟡 |
| 6 | **LlamaIndex** | `OpenAILike(api_base=...)` from `llama_index.llms.openai_like` | `runners/llamaindex/tasks/task*.py` | 🟡 |

## ✅ Resolved: Colmena reaches the proxy via the base_url patch (2026-06-11)

The finding below was fixed. A ~30-line patch to Colmena (`feat/llm-base-url-override`
branch) makes `LlmProviderFactory::create` honour per-provider base_url env
vars (`OPENAI_BASE_URL`, `GEMINI_BASE_URL`, `ANTHROPIC_BASE_URL`, with a
`COLMENA_LLM_BASE_URL` catch-all). See the plan at
`docs/superpowers/plans/2026-06-10-colmena-base-url-override.md`.

**Proven approach (smoke-tested 2026-06-11):** drive Colmena through its
**OpenAI adapter** against the proxy's OpenAI-compatible `/v1` route — the same
path the Python runners use, which our span callback already captures. Set
`OPENAI_BASE_URL=http://127.0.0.1:4000/v1` **before constructing `ColmenaLlm`**
(the factory reads it at build time), then:

```python
import os
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:4000/v1"  # before construction
import colmena
llm = colmena.ColmenaLlm()
opts = colmena.LlmConfigOptions()
opts.model = "gemini-2.5-flash"        # proxy maps this alias
opts.api_key = "<proxy master key>"    # proxy holds the real Google key
out = llm.call([{"role": "user", "content": "..."}], "openai", opts)
```

Result: the proxy captured the span (`gemini-2.5-flash`, 8 in / 18 out,
`ok=true`). The Gemini native pass-through (below) was **not needed** — the
OpenAI-dialect path is simpler and reuses proven infrastructure.

**Open follow-up (does not block base_url):** Colmena's OpenAI adapter does
not forward custom HTTP headers, so the `x-bench-run-id` per-run correlation
trick (used by the Python runners) doesn't apply. For now, correlate Colmena
spans by starting the proxy with `BENCH_RUN_ID=<run_id>` per run. A cleaner
fix is a small Colmena change to forward an extra header from an env var —
tracked separately. Also: the Colmena bench *runner* still needs to be wired
to drive `import colmena` (it currently scaffolds a non-existent CLI) — that's
bench task T12.1, independent of this base_url work.

---

## ⚠️ Original finding: Colmena could not reach the proxy on `develop` (2026-06-10)

Source inspection of `Startti/colmena` @ `develop`:

- The LLM client is selected by `LlmProviderFactory::create(kind)` in
  `src/libs/colmena/src/llm/infrastructure/llm_provider_factory.rs`.
- It hardcodes the default adapters: `GeminiAdapter::new()`,
  `OpenAiAdapter::new()`, `AnthropicAdapter::new()` — each of which bakes in
  the provider's production URL (e.g. `https://generativelanguage.googleapis.com/v1beta`).
- Both public entry points route through this factory:
  - `runDag(file)` → llm node at `dag_engine/.../nodes/llm.rs:1653` calls `LlmProviderFactory::create(...)`
  - `ColmenaLlm.call(...)` → same factory.
- There is **no env var and no config field** for the LLM endpoint. The only
  override is `set_test_override()` — `#[doc(hidden)]`, Rust-test-only,
  unreachable from the Node/Python bindings.
- `NodeLlmConfigOptions` (the binding's options struct) has `apiKey, model,
  temperature, maxTokens, topP, frequency/presencePenalty` — **no `baseUrl`**.

**Consequence:** Colmena's LLM calls go straight to the providers, bypassing
the LiteLLM proxy. We cannot capture Colmena's tokens the same
(provider-authoritative) way as the other 5 frameworks. This is the exact
risk in the risk register ("Framework hardcodes provider URL").

**Good news — the fix is ~10 lines.** All three adapters already expose
`with_base_url(String)` (verified: `openai_adapter.rs:32`,
`anthropic_adapter.rs:34`, `gemini_adapter.rs:32`). The factory just needs to
read an env var and use it:

```rust
// llm_provider_factory.rs
fn base_url_override(kind: ProviderKind) -> Option<String> {
    // e.g. COLMENA_LLM_BASE_URL routes every provider through one proxy.
    std::env::var("COLMENA_LLM_BASE_URL").ok()
}

match kind {
    ProviderKind::Google => match base_url_override(kind) {
        Some(u) => Arc::new(GeminiAdapter::with_base_url(u)),
        None => Arc::new(GeminiAdapter::new()),
    },
    // ... same for OpenAi / Anthropic
}
```

With that env var honored, Colmena becomes a first-class proxy citizen and
measurement stays symmetric across all 6 frameworks. **This is a patch to the
`colmena` repo, tracked here as a bench prerequisite.** Until it lands, the
Colmena runner cannot be gated by `verify_baseline.sh`.

## ⚠️ Finding: "native providers" bypass the proxy (2026-06-10)

CrewAI 1.x (and likely others) ship **native provider** clients. When you
write `LLM(model="gemini-2.5-flash")`, CrewAI loads `GeminiCompletion`, which
talks **straight to Google** and ignores `base_url` entirely — same failure
mode as Colmena, just opt-out-able. Symptom observed:
`ImportError: Google Gen AI native provider not available`.

**Fix (universal pattern for all Python runners):** prefix the model with
`openai/`. This forces the OpenAI-compatible HTTP path that honours
`base_url`. Our LiteLLM proxy speaks OpenAI dialect for every alias, so
`openai/gemini-2.5-flash` reaches the proxy, which resolves the alias to the
real provider model. Verified: CrewAI run reported 77/43 tokens, matching the
proxy span exactly.

Rule of thumb: **never let a runner name a provider-native model directly.**
Always go through `openai/<alias>` + `base_url=<proxy>`. Each runner's
hello-world gate must assert a span landed, or the bypass goes unnoticed.

## Standard snippet per framework

All runners receive these via env (see `.env.example`):

```bash
LITELLM_PROXY_BASE_URL=http://127.0.0.1:4000
LITELLM_PROXY_API_KEY=sk-bench-runner-do-not-use-in-prod
```

### CrewAI

```python
import os
from crewai import LLM

llm = LLM(
    model="gemini-2.5-flash",
    base_url=os.environ["LITELLM_PROXY_BASE_URL"],
    api_key=os.environ["LITELLM_PROXY_API_KEY"],
    temperature=0.0,
)
```

### LangChain / LangGraph

```python
import os
from langchain_openai import ChatOpenAI  # OpenAI-compatible endpoint

llm = ChatOpenAI(
    model="gemini-2.5-flash",
    base_url=os.environ["LITELLM_PROXY_BASE_URL"],
    api_key=os.environ["LITELLM_PROXY_API_KEY"],
    temperature=0.0,
)
```

> **Note:** we deliberately use `ChatOpenAI` against the LiteLLM proxy
> instead of `langchain_google_genai.ChatGoogleGenerativeAI`. The Google
> wrapper bypasses any HTTP override and talks directly to Google's API,
> which would skip our token capture. The proxy speaks OpenAI dialect for
> every model alias, so this is the correct path. T04 hello-LLM tests must
> confirm this for each framework.

### Google ADK

```python
import os
from google.adk.models.lite_llm import LiteLlm

llm = LiteLlm(
    model="gemini-2.5-flash",
    api_base=os.environ["LITELLM_PROXY_BASE_URL"],
    api_key=os.environ["LITELLM_PROXY_API_KEY"],
)
```

### LlamaIndex

```python
import os
from llama_index.llms.openai_like import OpenAILike

llm = OpenAILike(
    model="gemini-2.5-flash",
    api_base=os.environ["LITELLM_PROXY_BASE_URL"],
    api_key=os.environ["LITELLM_PROXY_API_KEY"],
    is_chat_model=True,
    temperature=0.0,
)
```

### Colmena

```json
{
  "llm": {
    "provider": "openai",
    "model": "gemini-2.5-flash",
    "base_url": "${LITELLM_PROXY_BASE_URL}",
    "api_key": "${LITELLM_PROXY_API_KEY}",
    "temperature": 0.0
  }
}
```

## Known risks (track here, escalate early)

| Framework | Risk | Mitigation |
|---|---|---|
| Google ADK | `LiteLlm` wrapper exists but ADK 2.x renamed several params vs 1.x. Verify `api_base` is the active spelling on 2.2.0. | Hello-LLM call + read 2.2.0 release notes. |
| LangChain | `langchain-google-genai` would bypass the proxy. Test must assert spans landed for every call. | Use `ChatOpenAI`-against-proxy, banned `langchain-google-genai` for hot path. |
| CrewAI | Some agent paths construct an internal LLM if not passed explicitly. | Pass `llm=...` to every `Agent`, `Task`, and `Crew`. Spans assertion. |
| LlamaIndex | Default `OpenAI` wrapper has subtly different chat formatting vs `OpenAILike`. | Stick to `OpenAILike` and verify the proxy receives a chat-completions payload. |
| Colmena | If Colmena uses its own HTTP client per call, `base_url` may be cached at agent init. | Restart Colmena process between runs (handled by orchestrator). |

## How to verify (when keys are available)

For each framework runner, after `pip install -e runners/<framework>`:

```bash
# 1. Start the proxy (separate terminal):
BENCH_RUN_ID=t04-$(date +%s) ./proxy/start_proxy.sh

# 2. From the framework venv, run a one-line LLM call:
python -c "..."   # snippet from above with .invoke('ping')

# 3. Confirm the span landed:
tail -n1 proxy/spans/run-t04-*.jsonl | jq '{model_alias, tokens_input, tokens_output, ok}'
```

Flip the row to ✅ once a non-zero `tokens_output` span lands. If `ok=false`
or no span lands at all, the framework is hardcoding the provider URL —
escalate before continuing with its runner.
