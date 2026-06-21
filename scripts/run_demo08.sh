#!/usr/bin/env bash
# run_demo08.sh — Demo #8 (sandboxed code-execution) one-command driver.
#
# Owns the proxy lifecycle: sources .env, kills any existing proxy, starts a
# fresh LiteLLM proxy with BENCH_RUN_ID=demo08, waits for readiness, runs
# the benchmark driver across all 6 frameworks, then kills the proxy on exit.
#
# Usage:
#   bash scripts/run_demo08.sh
#   bash scripts/run_demo08.sh --frameworks "colmena langchain" --variants S
#   bash scripts/run_demo08.sh --modes analytics,probe
#
# Requires: setup_all.sh already run; .env with keys + LITELLM_MASTER_KEY +
# COLMENA_DATABASE_URL + SECURE_VALUES_KEY (for the Colmena engine).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env so the driver's subprocess env carries COLMENA_DATABASE_URL +
# SECURE_VALUES_KEY (and all other required keys).
if [[ -f "$REPO_ROOT/.env" ]]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

BENCH_PY="$REPO_ROOT/.venv-bench/bin/python"
[[ -x "$BENCH_PY" ]] || { echo "✗ .venv-bench missing — run scripts/setup_all.sh"; exit 2; }

SESSION_ID="demo08"

mkdir -p "$REPO_ROOT/proxy/spans" "$REPO_ROOT/runs/demo08"

echo "[run_demo08] starting proxy (BENCH_RUN_ID=$SESSION_ID)"

# Kill any existing proxy, start fresh.
pkill -f "litellm --config" 2>/dev/null || true
sleep 1

PATH="$REPO_ROOT/.venv-bench/bin:$PATH" \
  BENCH_RUN_ID="$SESSION_ID" \
  nohup bash "$REPO_ROOT/proxy/start_proxy.sh" > /tmp/run_demo08_proxy.log 2>&1 &

trap 'pkill -f "litellm --config" 2>/dev/null || true' EXIT

# Wait up to 30 s for the proxy to become ready.
for i in $(seq 1 30); do
  curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 \
  || { echo "✗ proxy did not become ready (see /tmp/run_demo08_proxy.log)"; exit 1; }
echo "[run_demo08] proxy ready"

# Export PROXY_BENCH_RUN_ID so the driver can find the colmena session spans file.
export PROXY_BENCH_RUN_ID="$SESSION_ID"

# Run the driver, forwarding all extra CLI args (--frameworks, --variants, etc.).
PYTHONPATH="$REPO_ROOT/harness" \
  "$BENCH_PY" -m orchestrator.demo_codeexec_run "$@"

rc=$?
echo "[run_demo08] done → $REPO_ROOT/runs/demo08/summary.{json,csv}"
exit $rc
