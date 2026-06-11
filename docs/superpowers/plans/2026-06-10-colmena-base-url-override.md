# Colmena base_url Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Colmena's LLM adapters be pointed at a local proxy via environment variables, so colmena-bench can route every Colmena LLM call through the LiteLLM proxy for provider-authoritative token capture.

**Architecture:** Centralize base_url resolution in `LlmProviderFactory::create` (the single chokepoint all 12 call sites flow through). A pure helper reads per-provider env vars (`OPENAI_BASE_URL`, `GEMINI_BASE_URL`, `ANTHROPIC_BASE_URL`) with a `COLMENA_LLM_BASE_URL` catch-all fallback; when set, the factory builds the adapter with `with_base_url()` instead of `new()`. Zero behaviour change when no env var is set. Each adapter keeps its own provider dialect, so the bench points each at the proxy's matching pass-through route.

**Tech Stack:** Rust (the `colmena` crate at `src/libs/colmena`), NAPI-RS (Node binding), PyO3 + maturin (Python binding), LiteLLM proxy (bench side).

**Repos involved:**
- **`/Users/danielgarcia/startti/colmena`** — the Colmena library (Tasks 1-5). Branch `develop`.
- **`/Users/danielgarcia/startti/colmena-bench`** — the benchmark (Task 6, integration). Branch `phase-0-foundation` or a new branch.

---

## Why per-provider env vars (read before starting)

Colmena's adapters are **not** OpenAI-compatible clients. `GeminiAdapter` speaks the Gemini REST dialect (`{base_url}/models/{model}:generateContent`), `AnthropicAdapter` speaks Anthropic's `/v1/messages`, `OpenAiAdapter` speaks OpenAI's `/v1/chat/completions`. Overriding `base_url` is **dialect-preserving**: it only changes the host, not the wire format. Therefore:

- A single shared base_url pointed at an OpenAI-only endpoint would send Gemini-dialect bytes to an OpenAI route and fail.
- The proxy must expose a **pass-through route per dialect** (LiteLLM supports `/gemini`, `/anthropic`, `/v1` — configured in Task 6).
- So each adapter needs its own base_url. Per-provider env vars (`OPENAI_BASE_URL`, etc.) are the industry convention (the OpenAI and Anthropic SDKs read exactly these names) and match Colmena's existing per-provider `*_API_KEY` convention.

`COLMENA_LLM_BASE_URL` is offered as a convenience fallback for the rare case where one host fronts all three dialects on the same base path; per-provider vars take precedence.

---

## File Structure

**Colmena repo (`/Users/danielgarcia/startti/colmena`):**

- Modify: `src/libs/colmena/src/llm/infrastructure/llm_provider_factory.rs` — add `base_url_override(ProviderKind) -> Option<String>` helper + wire into `create()`. New unit tests in the same file's `#[cfg(test)]` module.
- Modify: `src/libs/colmena/src/llm/infrastructure/openai_adapter.rs` — add `pub fn base_url(&self) -> &str` getter.
- Modify: `src/libs/colmena/src/llm/infrastructure/gemini_adapter.rs` — same getter.
- Modify: `src/libs/colmena/src/llm/infrastructure/anthropic_adapter.rs` — same getter.

**colmena-bench repo (`/Users/danielgarcia/startti/colmena-bench`):**

- Modify: `proxy/litellm_config.yaml` — add pass-through routes for Gemini/Anthropic/OpenAI native dialects.
- Modify: `runners/colmena/src/engine.rs` — set the base_url env vars when spawning Colmena (or document that the orchestrator sets them).
- Modify: `.env.example` — document `GEMINI_BASE_URL` etc.
- Modify: `docs/base_url_compatibility.md` — flip Colmena row to ✅.

---

## Task 1: Pure helper — `base_url_override`

**Files:**
- Modify: `/Users/danielgarcia/startti/colmena/src/libs/colmena/src/llm/infrastructure/llm_provider_factory.rs` (add helper + tests)

The helper is a pure function of `ProviderKind` + the process environment. Isolating it makes the env-var precedence logic unit-testable without constructing trait objects.

- [ ] **Step 1: Write the failing tests**

Add this to the bottom of `llm_provider_factory.rs`, inside (or appending to) the existing `#[cfg(test)] mod tests { ... }` block. If no test module exists yet, create one. These tests mutate process env, so they must serialize on the factory's existing `override_lock()` to avoid cross-test races.

```rust
#[cfg(test)]
mod base_url_override_tests {
    use super::*;
    use crate::llm::domain::ProviderKind;

    // All env-mutating tests serialize on the factory override lock so they
    // never run concurrently with each other or with override tests.
    fn with_clean_env<F: FnOnce()>(f: F) {
        let _lock = match LlmProviderFactory::override_lock().lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        for k in ["OPENAI_BASE_URL", "GEMINI_BASE_URL", "ANTHROPIC_BASE_URL", "COLMENA_LLM_BASE_URL"] {
            std::env::remove_var(k);
        }
        f();
        for k in ["OPENAI_BASE_URL", "GEMINI_BASE_URL", "ANTHROPIC_BASE_URL", "COLMENA_LLM_BASE_URL"] {
            std::env::remove_var(k);
        }
    }

    #[test]
    fn none_when_no_env_set() {
        with_clean_env(|| {
            assert_eq!(base_url_override(ProviderKind::Google), None);
            assert_eq!(base_url_override(ProviderKind::OpenAi), None);
            assert_eq!(base_url_override(ProviderKind::Anthropic), None);
        });
    }

    #[test]
    fn per_provider_var_wins() {
        with_clean_env(|| {
            std::env::set_var("GEMINI_BASE_URL", "http://127.0.0.1:4000/gemini/v1beta");
            std::env::set_var("COLMENA_LLM_BASE_URL", "http://catchall");
            assert_eq!(
                base_url_override(ProviderKind::Google),
                Some("http://127.0.0.1:4000/gemini/v1beta".to_string())
            );
        });
    }

    #[test]
    fn catchall_used_when_no_per_provider_var() {
        with_clean_env(|| {
            std::env::set_var("COLMENA_LLM_BASE_URL", "http://catchall");
            assert_eq!(
                base_url_override(ProviderKind::Anthropic),
                Some("http://catchall".to_string())
            );
        });
    }

    #[test]
    fn mock_and_generated_never_overridden() {
        with_clean_env(|| {
            std::env::set_var("COLMENA_LLM_BASE_URL", "http://catchall");
            assert_eq!(base_url_override(ProviderKind::Mock), None);
            assert_eq!(base_url_override(ProviderKind::Generated), None);
        });
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/danielgarcia/startti/colmena && cargo test -p colmena base_url_override_tests 2>&1 | tail -20`
Expected: FAIL — compile error `cannot find function base_url_override in this scope`.

- [ ] **Step 3: Write the helper**

Add this function to `llm_provider_factory.rs`, above the `impl LlmProviderFactory` block (it's a free function in the module):

```rust
/// Resolve a base_url override for `kind` from the environment.
///
/// Precedence: the provider-specific var (`OPENAI_BASE_URL`,
/// `GEMINI_BASE_URL`, `ANTHROPIC_BASE_URL`) wins; otherwise the
/// `COLMENA_LLM_BASE_URL` catch-all applies. `Mock` and `Generated` are
/// never overridden — they don't make network calls.
///
/// Returns `None` when no relevant var is set, preserving the hardcoded
/// production defaults baked into each adapter's `new()`.
fn base_url_override(kind: ProviderKind) -> Option<String> {
    let per_provider = match kind {
        ProviderKind::OpenAi => Some("OPENAI_BASE_URL"),
        ProviderKind::Google => Some("GEMINI_BASE_URL"),
        ProviderKind::Anthropic => Some("ANTHROPIC_BASE_URL"),
        ProviderKind::Mock | ProviderKind::Generated => None,
    }?;
    if let Ok(url) = std::env::var(per_provider) {
        if !url.is_empty() {
            return Some(url);
        }
    }
    match std::env::var("COLMENA_LLM_BASE_URL") {
        Ok(url) if !url.is_empty() => Some(url),
        _ => None,
    }
}
```

Make sure `ProviderKind` is imported at the top of the file. The exploration shows the factory already imports adapters; add `use crate::llm::domain::ProviderKind;` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/danielgarcia/startti/colmena && cargo test -p colmena base_url_override_tests 2>&1 | tail -20`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/danielgarcia/startti/colmena
git add src/libs/colmena/src/llm/infrastructure/llm_provider_factory.rs
git commit -m "feat(llm): add base_url_override env-var resolver helper"
```

---

## Task 2: Wire the helper into the factory

**Files:**
- Modify: `/Users/danielgarcia/startti/colmena/src/libs/colmena/src/llm/infrastructure/llm_provider_factory.rs:24-31` (the `match kind` block in `create`)

- [ ] **Step 1: Add the `base_url()` getters the integration test needs**

The factory returns `Arc<dyn LlmRepository>`, which can't be downcast to read `base_url`. To prove wiring works we add a small getter to each adapter and assert via a concrete-type construction test in Task 3. For now, add the getter to all three adapters.

In `openai_adapter.rs`, inside `impl OpenAiAdapter`, after `with_base_url`:

```rust
    /// The configured endpoint. Exposed for tests and diagnostics.
    pub fn base_url(&self) -> &str {
        &self.base_url
    }
```

In `gemini_adapter.rs`, inside `impl GeminiAdapter`, after `with_base_url`:

```rust
    /// The configured endpoint. Exposed for tests and diagnostics.
    pub fn base_url(&self) -> &str {
        &self.base_url
    }
```

In `anthropic_adapter.rs`, inside `impl AnthropicAdapter`, after `with_base_url`:

```rust
    /// The configured endpoint. Exposed for tests and diagnostics.
    pub fn base_url(&self) -> &str {
        &self.base_url
    }
```

- [ ] **Step 2: Modify `create()` to use the override**

Replace the `match kind` block in `LlmProviderFactory::create` (currently lines ~24-31) with:

```rust
        match kind {
            ProviderKind::OpenAi => match base_url_override(ProviderKind::OpenAi) {
                Some(url) => Arc::new(OpenAiAdapter::with_base_url(url)),
                None => Arc::new(OpenAiAdapter::new()),
            },
            ProviderKind::Google => match base_url_override(ProviderKind::Google) {
                Some(url) => Arc::new(GeminiAdapter::with_base_url(url)),
                None => Arc::new(GeminiAdapter::new()),
            },
            ProviderKind::Anthropic => match base_url_override(ProviderKind::Anthropic) {
                Some(url) => Arc::new(AnthropicAdapter::with_base_url(url)),
                None => Arc::new(AnthropicAdapter::new()),
            },
            ProviderKind::Mock => Arc::new(MockAdapter::new()),
            ProviderKind::Generated => Arc::new(MockAdapter::new()),
        }
```

- [ ] **Step 3: Build to verify it compiles**

Run: `cd /Users/danielgarcia/startti/colmena && cargo build -p colmena 2>&1 | tail -15`
Expected: compiles (warnings OK). The `base_url()` getters may warn as unused until Task 3's test — acceptable, or add `#[allow(dead_code)]` if the build denies warnings.

- [ ] **Step 4: Run the full factory test module**

Run: `cd /Users/danielgarcia/startti/colmena && cargo test -p colmena base_url 2>&1 | tail -20`
Expected: PASS — the override helper tests still green.

- [ ] **Step 5: Commit**

```bash
cd /Users/danielgarcia/startti/colmena
git add src/libs/colmena/src/llm/infrastructure/
git commit -m "feat(llm): factory honours base_url env vars; add base_url() getters"
```

---

## Task 3: Integration test — adapter built with override carries the URL

**Files:**
- Modify: `/Users/danielgarcia/startti/colmena/src/libs/colmena/src/llm/infrastructure/gemini_adapter.rs` (add a `#[cfg(test)]` test)

The factory returns a trait object, so the cleanest end-to-end assertion of "override → adapter URL" is at the adapter level: construct via `with_base_url` and read it back. This locks the contract the factory depends on.

- [ ] **Step 1: Write the failing test**

Append to `gemini_adapter.rs` (inside its existing `#[cfg(test)] mod tests`, or create one):

```rust
#[cfg(test)]
mod base_url_tests {
    use super::*;

    #[test]
    fn new_uses_production_default() {
        let a = GeminiAdapter::new();
        assert_eq!(a.base_url(), "https://generativelanguage.googleapis.com/v1beta");
    }

    #[test]
    fn with_base_url_overrides() {
        let a = GeminiAdapter::with_base_url("http://127.0.0.1:4000/gemini/v1beta".to_string());
        assert_eq!(a.base_url(), "http://127.0.0.1:4000/gemini/v1beta");
    }
}
```

- [ ] **Step 2: Run to verify it fails (if getter missing) or passes**

Run: `cd /Users/danielgarcia/startti/colmena && cargo test -p colmena base_url_tests 2>&1 | tail -15`
Expected: PASS (getter added in Task 2). If FAIL with "no method base_url", revisit Task 2 Step 1.

- [ ] **Step 3: Commit**

```bash
cd /Users/danielgarcia/startti/colmena
git add src/libs/colmena/src/llm/infrastructure/gemini_adapter.rs
git commit -m "test(llm): lock GeminiAdapter base_url default + override"
```

---

## Task 4: Rebuild the native modules

**Files:** none modified — this builds the Node `.node` and Python module so the bench can import the change.

- [ ] **Step 1: Build the Node native module**

Run: `cd /Users/danielgarcia/startti/colmena && npm run build 2>&1 | tail -15`
Expected: produces `colmena.darwin-arm64.node` (or platform equivalent) in the repo root, exit 0.

- [ ] **Step 2: Build + install the Python module into the bench venv**

The bench uses `.venv-bench` (Python 3.11). Build the Python wheel against it:

Run:
```bash
cd /Users/danielgarcia/startti/colmena
VIRTUAL_ENV=/Users/danielgarcia/startti/colmena-bench/.venv-bench \
  /opt/homebrew/bin/uv run --project /Users/danielgarcia/startti/colmena-bench maturin develop --release 2>&1 | tail -20
```
If `uv run maturin` is awkward, instead: `VIRTUAL_ENV=.../.venv-bench uv pip install maturin && .../.venv-bench/bin/maturin develop --release --manifest-path src/libs/colmena/Cargo.toml`.
Expected: `🛠 Installed colmena-ai`, module importable as `import colmena`.

- [ ] **Step 3: Smoke-test the import + default behaviour (no override)**

Run:
```bash
/Users/danielgarcia/startti/colmena-bench/.venv-bench/bin/python -c "import colmena; print('ok', [m for m in dir(colmena) if not m.startswith('_')][:8])"
```
Expected: prints `ok [...]` including `ColmenaLlm`.

- [ ] **Step 4: Commit (lock file / build artifacts as the repo convention dictates)**

```bash
cd /Users/danielgarcia/startti/colmena
git add -A
git commit -m "build: rebuild native modules with base_url override" || echo "nothing to commit"
```

---

## Task 5: Live verification — Colmena call routes through the proxy

**Files:** none — this is a manual end-to-end check proving token capture works. Requires the bench proxy running with a Gemini pass-through route (Task 6) and real keys in `.env`.

> Do Task 6 first if the proxy has no Gemini pass-through route yet — this task depends on it.

- [ ] **Step 1: Start the bench proxy**

Run (in a separate terminal):
```bash
cd /Users/danielgarcia/startti/colmena-bench
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID=colmena-smoke bash proxy/start_proxy.sh
```
Expected: `✓ ready`, models loaded.

- [ ] **Step 2: Call Colmena's LLM through the proxy from Python**

Run:
```bash
cd /Users/danielgarcia/startti/colmena-bench
rm -f proxy/spans/run-colmena-smoke.jsonl
GEMINI_BASE_URL="http://127.0.0.1:4000/gemini/v1beta" \
GEMINI_API_KEY="$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)" \
BENCH_RUN_ID=colmena-smoke \
.venv-bench/bin/python -c "
import colmena, asyncio
llm = colmena.ColmenaLlm()
out = llm.call(messages=['Respond with the single word: hello'], provider='gemini')
# call may return a coroutine (python binding) — await if so
import inspect
if inspect.iscoroutine(out): out = asyncio.get_event_loop().run_until_complete(out)
print('ANSWER:', out)
"
```
Expected: prints `ANSWER: hello` (or similar). NOTE: pass the proxy master key as `GEMINI_API_KEY` because the proxy validates that bearer; the proxy holds the real Google key.

- [ ] **Step 3: Confirm the proxy captured the span**

Run: `cat /Users/danielgarcia/startti/colmena-bench/proxy/spans/run-colmena-smoke.jsonl | jq -c '{provider_model, tokens_input, tokens_output, ok}'`
Expected: a span with `tokens_input > 0`, `tokens_output > 0`, `ok: true`. **This proves Colmena now routes through the proxy** — the whole point.

- [ ] **Step 4: If no span appears**

The Gemini pass-through route in the proxy isn't matching the adapter's dialect. Inspect the proxy log for the inbound path and adjust the pass-through route in `proxy/litellm_config.yaml` (Task 6) until the path the adapter posts to (`{GEMINI_BASE_URL}/models/...:generateContent`) maps to a configured route. Re-run Step 2.

---

## Task 6: Bench integration — proxy pass-through + runner wiring (colmena-bench repo)

**Files:**
- Modify: `/Users/danielgarcia/startti/colmena-bench/proxy/litellm_config.yaml`
- Modify: `/Users/danielgarcia/startti/colmena-bench/.env.example`
- Modify: `/Users/danielgarcia/startti/colmena-bench/runners/colmena/src/engine.rs`
- Modify: `/Users/danielgarcia/startti/colmena-bench/docs/base_url_compatibility.md`

- [ ] **Step 1: Add Gemini pass-through to the proxy config**

LiteLLM exposes provider pass-through routes that accept a provider's native dialect and forward it (capturing tokens). Add to `proxy/litellm_config.yaml` under a top-level key:

```yaml
# Pass-through routes: accept each provider's NATIVE dialect (Colmena's
# adapters speak Gemini/Anthropic/OpenAI wire formats, not OpenAI-only).
# The proxy forwards to the real provider and still logs spans via the
# success/failure callback. Bench points GEMINI_BASE_URL etc. at these.
pass_through_endpoints:
  - path: "/gemini"
    target: "https://generativelanguage.googleapis.com"
    headers:
      x-goog-api-key: "os.environ/GEMINI_API_KEY"
```

> Verify against the installed LiteLLM 1.88.1 pass-through docs — the exact
> key names (`pass_through_endpoints`, `target`) are version-sensitive. If the
> callback does not fire for pass-through routes in this version, fall back to
> the alternative in Step 1b.

- [ ] **Step 1b (fallback): OpenAI-dialect adapter**

If LiteLLM pass-through doesn't emit spans in 1.88.1, the alternative is to make Colmena's bench runs use the **OpenAI adapter pointed at the OpenAI-compatible proxy route** (`/v1`), i.e. set `OPENAI_BASE_URL=http://127.0.0.1:4000/v1` and drive Colmena with `provider="openai"`, `model="gemini-2.5-flash"`. The proxy's existing `model_list` already maps that alias. This reuses the proven OpenAI path (same one CrewAI uses) and needs no pass-through config. Document whichever path is chosen in `docs/base_url_compatibility.md`.

- [ ] **Step 2: Document the env vars in `.env.example`**

Add under the LiteLLM proxy section of `.env.example`:

```bash
# Colmena base_url overrides — point Colmena's native adapters at the proxy.
# Per-provider (industry convention). Leave unset for production (direct).
GEMINI_BASE_URL=http://127.0.0.1:4000/gemini/v1beta
# OPENAI_BASE_URL=http://127.0.0.1:4000/v1
# ANTHROPIC_BASE_URL=http://127.0.0.1:4000/anthropic
# Catch-all fallback if one host fronts all dialects:
# COLMENA_LLM_BASE_URL=
```

- [ ] **Step 3: Set the env vars when the Colmena runner spawns**

In `runners/colmena/src/engine.rs`, the runner builds the `Command` for Colmena. Add the base_url env var so the spawned Colmena process inherits it. Locate the `Command::new("colmena")` / library-call setup and add before spawn:

```rust
    // Route Colmena's LLM calls through the bench proxy so tokens are
    // captured (METHODOLOGY §4). The proxy base URL arrives as
    // args.proxy_base_url; Colmena reads GEMINI_BASE_URL (see
    // docs/base_url_compatibility.md and the colmena base_url patch).
    let gemini_base = format!("{}/gemini/v1beta", args.proxy_base_url.trim_end_matches('/'));
    command.env("GEMINI_BASE_URL", gemini_base);
    command.env("BENCH_RUN_ID", &args.run_id);
```

> NOTE: the current `engine.rs` shells out to a `colmena` CLI that does not
> exist (Colmena is a library, not a CLI — see exploration). Reconciling that
> (library binding vs CLI) is tracked separately as T12.1; this step adds the
> env wiring wherever the spawn/library call ends up living.

- [ ] **Step 4: Run the gate with Colmena**

Once the runner can actually drive Colmena (T12.1) and the proxy route works:

Run:
```bash
cd /Users/danielgarcia/startti/colmena-bench
FRAMEWORKS=colmena N=3 PYTHON="$PWD/.venv-bench/bin/python" bash scripts/verify_baseline.sh 2>&1 | tail -20
```
Expected: `pass: colmena`, gate green — proxy↔runner token parity within ±2%.

- [ ] **Step 5: Flip the docs and commit**

Update `docs/base_url_compatibility.md` row 1 (Colmena) from ❌ to ✅ with the date and the env-var mechanism, and note whether the Gemini pass-through (Step 1) or the OpenAI-dialect fallback (Step 1b) was used.

```bash
cd /Users/danielgarcia/startti/colmena-bench
git add proxy/litellm_config.yaml .env.example runners/colmena/src/engine.rs docs/base_url_compatibility.md
git commit -m "feat(colmena): route Colmena LLM calls through proxy via GEMINI_BASE_URL"
```

---

## Self-Review notes

- **Spec coverage:** every requirement (env-var override, all call sites covered via the factory chokepoint, zero prod behaviour change, both bindings rebuilt, live token-capture proof, bench integration) maps to Tasks 1-6.
- **Type consistency:** `base_url_override(ProviderKind) -> Option<String>` used identically in Tasks 1 and 2; `base_url(&self) -> &str` getter defined in Task 2, asserted in Task 3.
- **Known open question (flagged, not hidden):** whether LiteLLM 1.88.1 pass-through routes fire the span callback. Task 6 Step 1b is the concrete fallback (OpenAI-dialect via the already-proven `/v1` path) if they don't — so the plan does not dead-end.
- **Dependency note:** Task 5 depends on Task 6 Step 1 (proxy route). The Colmena-only Tasks 1-4 are independent and can land first; they're the core deliverable.

## Risks

| Risk | Mitigation |
|---|---|
| LiteLLM pass-through doesn't log spans in 1.88.1 | Task 6 Step 1b: use OpenAI adapter against `/v1` (proven path) |
| Colmena runner shells out to a non-existent `colmena` CLI | T12.1 reconciliation (library binding) — env wiring in Task 6 Step 3 is placement-agnostic |
| Env-mutating Rust tests race | All serialize on `override_lock()` (Task 1 `with_clean_env`) |
| `base_url()` getters warn as dead code under `-D warnings` | Used by Task 3 test; add `#[allow(dead_code)]` if needed |
