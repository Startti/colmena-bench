# Runner contract

**Status**: final for v0.1. Breaking changes require a major bump and
re-running every captured runner output.

Every runner (Colmena Rust binary + 5 Python runners) must implement this
CLI contract. The orchestrator (`harness/orchestrator/run.py`) doesn't know
or care what's behind it.

## Invocation

```bash
<runner-binary>  \
  --task <path-to-task.yaml>  \
  --variant <variant-name>     \
  --run-id <uuid>              \
  --model-alias <gemini-2.5-flash|claude-haiku|gpt-4o-mini>  \
  --proxy-base-url <url>       \
  --output <path-to-run-output.json>
```

| Flag | Required | Description |
|---|---|---|
| `--task` | yes | Path to a task YAML conforming to `schemas/task.schema.json`. |
| `--variant` | yes | Variant name from the task YAML, or `default`. |
| `--run-id` | yes | UUIDv4. **Same value used in proxy spans file** for correlation. |
| `--model-alias` | yes | One of the 3 cross-validation aliases. |
| `--proxy-base-url` | yes | Where to send LLM calls. `http://127.0.0.1:4000` in local runs. |
| `--output` | yes | Where to write the run-output JSON. |
| `--timeout-seconds` | no | Hard wall clock cap. Default 300. Runner self-enforces and exits 124 on timeout. |

### Environment

The orchestrator sets these env vars before forking the runner:

| Var | Purpose |
|---|---|
| `BENCH_RUN_ID` | Same value as `--run-id`. Convenience for runner internals. |
| `LITELLM_PROXY_API_KEY` | Dummy bearer for the proxy. |
| `BENCH_DATASET_DIR` | Absolute path to the dataset variant directory. |

## Output

Runner writes exactly one JSON file at `--output`, conforming to
`schemas/run_output.schema.json`. Pretty-printed or minified — both fine.

The runner is responsible for:
- Measuring its own `latency_ms` (wall-clock) and `cold_start_ms` (process
  spawn → first instruction executed).
- Reporting framework-internal `tool_calls` count. The orchestrator
  cross-checks this against proxy spans (METHODOLOGY §4); a delta of more
  than 1 fails the run.
- Resolving `framework_version` at runtime (read from package metadata,
  not hardcoded).
- Filling `success.ok` per the task's `success.kind` rule.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Wrote a valid run-output, regardless of `success.ok`. |
| 1 | Runner crashed before writing output. Orchestrator should record a synthetic failed run. |
| 124 | Timeout. Runner self-killed. |
| Other | Treated as crash (code 1). |

## Stdout / stderr

- **stderr**: free-form logs, captured by orchestrator into `results/<date>/raw/<framework>/<run-id>.stderr`.
- **stdout**: must be empty *except* for an optional single JSON object
  reporting structured progress. Anything else fails the run.
  (This rule exists so that nothing accidentally pollutes parseable output
  in CI when stdout is captured.)

## Determinism expectations

- Same `--task`, same `--variant`, same `--model-alias`, same dataset → the
  answer payload may legitimately differ (LLM nondeterminism even at T=0
  for many providers), but **latency, tokens, cost should be within 5%** on
  the same hardware. The orchestrator runs N=30 repetitions and reports
  bootstrap CIs (METHODOLOGY §5).
- Runners must not seed the model — the proxy handles temperature & seed.

## Pre-flight self-check (T11 gate)

`scripts/verify_baseline.sh` runs Task 1 with N=3 against the first two
runners that exist (Colmena + CrewAI). For each run it asserts:

1. `run_output.json` validates against `run_output.schema.json`.
2. The proxy spans file `proxy/spans/run-<run-id>.jsonl` exists and has
   ≥1 line.
3. `sum(span.tokens_input + span.tokens_output)` matches
   `run_output.tokens.input + run_output.tokens.output` within ±2 %.
4. `run_output.tool_calls` is within ±1 of the proxy-counted tool calls.

If any of these fails, the harness is wrong and **no other runners ship**
until it's fixed. See `IMPLEMENTATION_PLAN.md` T11.

## Versioning the contract itself

This file's "v0.1" is the contract version. Bumping it bumps every
runner's expected behaviour. The orchestrator records the contract version
in `manifest.json` per benchmark run so old results stay interpretable.
