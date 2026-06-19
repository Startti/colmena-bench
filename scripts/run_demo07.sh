#!/usr/bin/env bash
# run_demo07.sh — Demo #7 (many-tools needle-in-haystack) sweep driver.
#
# Owns the proxy lifecycle (mirrors scripts/run_demo06.sh): sources .env, starts
# the LiteLLM proxy with a stable BENCH_RUN_ID=demo07 (so all of colmena's
# header-less engine spans land in proxy/spans/run-demo07.jsonl, which the driver
# measures by delta), waits for readiness, runs the sweep driver, then kills the
# proxy on exit. NO mask audit needed for this demo.
#
# All CLI args are passed through to the driver, so:
#   bash scripts/run_demo07.sh                                  # full default grid
#   bash scripts/run_demo07.sh --counts 5,50,200 --difficulties hard --trials 2
#
# Requires: setup_all.sh already run; .env with keys + LITELLM_MASTER_KEY +
# COLMENA_DATABASE_URL + SECURE_VALUES_KEY (the last two for the Colmena engine).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env so the driver's subprocess env carries COLMENA_DATABASE_URL +
# SECURE_VALUES_KEY (the Colmena engine needs them; competitors don't).
if [[ -f "$REPO_ROOT/.env" ]]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

BENCH_PY="$REPO_ROOT/.venv-bench/bin/python"
[[ -x "$BENCH_PY" ]] || { echo "✗ .venv-bench missing — run scripts/setup_all.sh"; exit 2; }

SESSION_ID="demo07"

mkdir -p "$REPO_ROOT/proxy/spans" "$REPO_ROOT/runs/demo07"

echo "[run_demo07] starting proxy (BENCH_RUN_ID=$SESSION_ID)"
pkill -f "litellm --config" 2>/dev/null || true
sleep 1
PATH="$REPO_ROOT/.venv-bench/bin:$PATH" \
  BENCH_RUN_ID="$SESSION_ID" \
  nohup bash "$REPO_ROOT/proxy/start_proxy.sh" > /tmp/run_demo07_proxy.log 2>&1 &
trap 'pkill -f "litellm --config" 2>/dev/null || true' EXIT

for i in $(seq 1 30); do
  curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 \
  || { echo "✗ proxy did not become ready (see /tmp/run_demo07_proxy.log)"; exit 1; }
echo "[run_demo07] proxy ready"

# --- drive the sweep (pass CLI args through, e.g. --counts/--difficulties) ----
PROXY_BENCH_RUN_ID="$SESSION_ID" \
  "$BENCH_PY" "$REPO_ROOT/harness/orchestrator/demo_tools_run.py" "$@"
rc=$?

echo "[run_demo07] done → $REPO_ROOT/runs/demo07/summary.{json,csv}"
exit $rc
