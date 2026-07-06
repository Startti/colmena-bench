# E-4 — the same Colmena engine, three languages

Colmena's DAG engine is a Rust core (`dag_engine::api::run_dag`) with three
language front doors, all calling that identical function:

| SDK | entrypoint | how it binds |
|---|---|---|
| **Rust** | `dag_engine run <file>` | the native CLI binary |
| **Python** | `colmena.run_dag(...)` | PyO3 binding (used by every Colmena runner in this benchmark) |
| **TypeScript/Node** | `colmena-ai` `runDag(...)` | napi binding published to npm |

`run_multilang.py` drives one deterministic DAG
(`graphs/power.json`: `mock_input(5) → exponential(³) → log ⇒ 125`, pure compute,
no LLM/DB/secrets) through all three and asserts the output is identical. This is
the evidence that the benchmark's Colmena arm is **not a Python-only artifact** —
the exact same engine is adoptable from whichever runtime a team's stack uses.

## Run it

```bash
export COLMENA_REPO=/path/to/colmena        # the colmena checkout
runners/colmena/.venv/bin/python harness/multilang/run_multilang.py
```

Writes `runs/demo_multilang/summary.json`. Exit 0 iff all run SDKs return the
identical (session-id-stripped, number-normalized) result.

## Prereqs (all produced by `scripts/setup_all.sh`)

- `COLMENA_REPO` set; `DATABASE_URL` / `COLMENA_DATABASE_URL` set (the engine
  builds a Postgres registry even though this compute DAG never touches the DB).
- Rust binary: `cargo build --release --bin dag_engine`.
- Python binding: `runners/colmena/.venv` (maturin develop).
- Node binding: `(cd $COLMENA_REPO && npm install && npm run build)` → the
  `colmena.<triple>.node` native module + `lib/` facade.

## Result (colmena `colmena_dag_engine-v0.9.0`)

All three return `{start:{input:5.0}, pow_step:{output:125.0}, log_result:125.0}`
— `identical_output: true`. See `runs/demo_multilang/summary.json`.
