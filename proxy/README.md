# LiteLLM proxy

Single chokepoint for every LLM call made by every runner during a benchmark.

## Why a proxy

- **Token capture is provider-authoritative**, not framework-reported. Frames
  lie about cached tokens; providers don't. METHODOLOGY §4 names the proxy
  as the source of truth.
- **Credentials never leak into framework code.** Runners get a dummy bearer
  and `LITELLM_PROXY_BASE_URL`; the proxy holds the real keys.
- **Model swaps without code changes.** Runners ask for the alias
  `gemini-2.5-flash` / `claude-haiku` / `gpt-4o-mini`; the proxy resolves to
  the real provider model.

## Start

```bash
cp .env.example .env   # then fill in real keys
./proxy/start_proxy.sh                       # foreground, spans → run-adhoc.jsonl
BENCH_RUN_ID=$(uuidgen) ./proxy/start_proxy.sh   # per-run span file
```

## Smoke test (T03 verification — blocked on real API keys)

```bash
# Once keys are filled in .env and the proxy is running:
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-bench-runner-do-not-use-in-prod" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [{"role": "user", "content": "ping"}]
  }' | jq .

# Verify the span was written:
tail -n1 proxy/spans/run-adhoc.jsonl | jq .
# Expect: tokens_input > 0, tokens_output > 0, ok=true, latency_ms > 0
```

The full smoke test that compares proxy-captured tokens vs runner-reported
counts is `scripts/verify_baseline.sh` (T11) and runs after the first two
runners exist (T12 + T13).

## Files

| File | Purpose |
|---|---|
| `litellm_config.yaml` | Model aliases, provider routing, callback wiring |
| `spans_callback.py` | Custom LiteLLM logger that appends one JSONL line per call |
| `start_proxy.sh` | Loads `.env`, wires `PYTHONPATH`, runs `litellm --config` |
| `spans/` | Output directory (gitignored except `.gitkeep`) |
