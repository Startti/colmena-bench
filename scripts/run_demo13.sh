#!/usr/bin/env bash
# run_demo13.sh — Demo #13 (Concurrency Ceiling) one-command driver.
#
# Thin wrapper over the load-test harness (harness/loadtest/) so the concurrency
# sweep is invoked like every other demo (scripts/run_demoN.sh). It sources .env,
# runs the phase-1 go/no-go sweep — Colmena Serve (thread-pooled) vs a warm async
# LangGraph FastAPI server, both against a fixed-latency mock LLM, so the only
# variable is how each runtime schedules concurrent requests — then renders the
# verdict. The sweep itself spends NO tokens (the mock replaces the provider).
#
# Usage:
#   bash scripts/run_demo13.sh
#   DURATION_S=15 CONCURRENCIES=1,2,4,8,16,32,64 bash scripts/run_demo13.sh
#
# Env passthrough (see harness/loadtest/run_phase1.sh): DELAY_MS, CONCURRENCIES,
# DURATION_S. If runs/demo13/calibration.json is absent a default mock delay is
# used. Requires: scripts/setup_all.sh already run (.venv-bench present); the
# Colmena Serve binary + the LangGraph server deps installed.
#
# Outputs: runs/demo13/phase1/{colmena,langgraph}.json and phase1/VERDICT.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env so the load-test servers inherit any local config (DB URL, keys); the
# sweep drives a mock, but the Colmena Serve process still boots the real engine.
if [[ -f "$REPO_ROOT/.env" ]]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

BENCH_PY="$REPO_ROOT/.venv-bench/bin/python"
[[ -x "$BENCH_PY" ]] || { echo "✗ .venv-bench missing — run scripts/setup_all.sh"; exit 2; }

echo "[run_demo13] concurrency sweep (Colmena Serve vs warm LangGraph, mock LLM, 0 tokens)"
bash "$REPO_ROOT/harness/loadtest/run_phase1.sh"

echo "[run_demo13] rendering verdict"
"$BENCH_PY" -m harness.loadtest.phase1_verdict

echo "[run_demo13] done → $REPO_ROOT/runs/demo13/phase1/{colmena,langgraph}.json + VERDICT.md"
