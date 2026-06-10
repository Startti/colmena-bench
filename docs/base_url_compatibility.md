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
| 1 | **Colmena** | Built-in OpenAI-compatible client; `base_url` parameter on the LLM provider config | `runners/colmena/tasks/*.json` → `llm.base_url` | 🟡 |
| 2 | **CrewAI** | `LLM(base_url=...)` from `crewai.llm` (LiteLLM under the hood) | `runners/crewai/tasks/task*.py` → `LLM(base_url=os.environ["LITELLM_PROXY_BASE_URL"], api_key="sk-bench-runner-do-not-use-in-prod")` | 🟡 |
| 3 | **LangChain** | `ChatOpenAI(base_url=...)` for OpenAI-style models, or `ChatLiteLLM` wrapper | `runners/langchain/tasks/task*.py` | 🟡 |
| 4 | **LangGraph** | Same as LangChain (LangGraph uses LangChain model wrappers) | `runners/langgraph/tasks/task*.py` | 🟡 |
| 5 | **Google ADK** | `LiteLlm(model=..., api_base=...)` wrapper from `google.adk.models.lite_llm` | `runners/google_adk/tasks/task*.py` | 🟡 |
| 6 | **LlamaIndex** | `OpenAILike(api_base=...)` from `llama_index.llms.openai_like` | `runners/llamaindex/tasks/task*.py` | 🟡 |

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
