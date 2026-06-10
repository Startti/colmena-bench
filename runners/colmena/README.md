# Colmena runner

Thin Rust wrapper that invokes Colmena to execute benchmark tasks and emits
the JSON contract defined in [`harness/runner_contract.md`](../../harness/runner_contract.md).

## Pointing at a Colmena revision

The Colmena dependency is declared once in [`Cargo.toml`](./Cargo.toml). All
local builds and CI runs flow through that single source of truth — never
edit `Cargo.lock` by hand. Pick **one** of the four modes below and commit
both `Cargo.toml` and the regenerated `Cargo.lock` together.

### 1. Track a branch (current default — `develop`)

Useful while Colmena is moving fast and the bench wants the latest changes.
**Not reproducible across days** — `Cargo.lock` pins the SHA, but the SHA
moves the next time someone runs `cargo update`.

```toml
[dependencies]
colmena = { git = "ssh://git@github.com/Startti/colmena.git", branch = "develop" }
```

To switch branch (e.g. to test a feature branch `feat/new-scheduler`):

```bash
# 1. Edit runners/colmena/Cargo.toml — change `branch = "..."`
# 2. Refresh the lock file so the new branch's HEAD is pinned
cd runners/colmena
cargo update -p colmena
cargo build
git add Cargo.toml Cargo.lock
git commit -m "colmena: track feat/new-scheduler"
```

### 2. Pin a tag (recommended for `v1.0` and later official runs)

Reproducible. Use once Colmena cuts a stable release.

```toml
[dependencies]
colmena = { git = "ssh://git@github.com/Startti/colmena.git", tag = "v0.4.0" }
```

### 3. Pin a specific commit SHA (most reproducible)

Use for whitepaper-grade runs where the exact commit must be auditable.

```toml
[dependencies]
colmena = { git = "ssh://git@github.com/Startti/colmena.git", rev = "abc1234def5678..." }
```

Find the SHA with:

```bash
git ls-remote ssh://git@github.com/Startti/colmena.git refs/heads/develop
```

### 4. Local path (development only)

Useful when you have a Colmena checkout next door and want to iterate on both
sides without pushing. **Never commit this** — it breaks every other dev's
build.

```toml
[dependencies]
# colmena = { path = "../../../colmena" }
```

## Reproducibility checklist

Before publishing benchmark results derived from this runner:

- [ ] `Cargo.toml` uses `tag` or `rev`, not `branch`
- [ ] `Cargo.lock` is committed
- [ ] The commit SHA recorded in `results/<date>/manifest.json` matches
      `cargo pkgid colmena`
- [ ] METHODOLOGY.md §1 shows the same SHA / tag

## Building

```bash
cd runners/colmena
cargo build --release
./target/release/colmena-bench-runner --help
```

## Integration mode (T12)

The runner currently **shells out to the `colmena` CLI** rather than
linking the Colmena crate. Rationale: Colmena's public-API surface is
still moving on `develop`; the CLI gives us a stable interop boundary
that's easy to debug from a shell.

Expected `colmena` CLI shape (the runner calls this; see `src/engine.rs`):

```bash
colmena run-task \
    --task <path/to/dag.json> \
    --prompt-stdin \
    --model <gemini-2.5-flash|claude-haiku|gpt-4o-mini> \
    --proxy-base-url http://127.0.0.1:4000 \
    --proxy-api-key sk-bench-runner-do-not-use-in-prod
```

`colmena` reads the prompt from **stdin** and must emit exactly one
JSON object on stdout:

```json
{"answer": "hello", "usage": {"input": 7, "output": 1, "cached": 0, "tool_calls": 0}}
```

If Colmena's actual CLI differs, update `src/engine.rs::run_task_01`
(not `runner_contract.md` — the contract is the same for every runner).

### Switching to library mode (T12.1, future)

Once the Colmena public API is locked, uncomment the `colmena = { git = ... }`
dependency in [`Cargo.toml`](./Cargo.toml) and replace `run_task_01` with
a direct library call. The contract surface (args + emitted JSON) is the
same, so `verify_baseline.sh` will pass without changes.

## DAGs

Per-task DAGs live in [`tasks/`](./tasks). Each one is a tiny JSON file
that Colmena accepts as a workflow description. Currently:

| Task | File | Notes |
|---|---|---|
| `01_hello_world` | `tasks/01_hello_world.json` | Single LLM node, no tools |
