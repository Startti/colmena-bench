#!/usr/bin/env bash
# run_demo06.sh — Demo #4 (refund agent) one-command driver.
#
# Owns the proxy lifecycle (mirrors scripts/run_task.sh): sources .env, starts the
# LiteLLM proxy with the masking-audit secret armed, waits for readiness, runs the
# two-process driver across all 4 frameworks, then kills the proxy on exit.
#
# Usage:
#   bash scripts/run_demo06.sh
#   bash scripts/run_demo06.sh --frameworks "colmena crewai"
#
# Requires: setup_all.sh already run; .env with keys + LITELLM_MASTER_KEY +
# COLMENA_DATABASE_URL + SECURE_VALUES_KEY (the last two for the Colmena engine).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env so the driver's subprocess env carries COLMENA_DATABASE_URL +
# SECURE_VALUES_KEY (the Colmena refund DAG copies COLMENA_DATABASE_URL →
# DATABASE_URL at run_dag time). The 3 competitor runners don't need them.
if [[ -f "$REPO_ROOT/.env" ]]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

BENCH_PY="$REPO_ROOT/.venv-bench/bin/python"
[[ -x "$BENCH_PY" ]] || { echo "✗ .venv-bench missing — run scripts/setup_all.sh"; exit 2; }

# The masking-audit secret the proxy callback scans request bodies for. Must match
# scenario_refund.SECRET (the value the payment tool returns).
MASK_SECRET="sk-live-REFUND-SECRET-abc123"
SESSION_ID="demo06"

mkdir -p "$REPO_ROOT/proxy/spans" "$REPO_ROOT/runs/demo06"

echo "[run_demo06] starting proxy (mask audit armed)"
# --- start proxy with the mask-audit secret + a stable BENCH_RUN_ID ----------
pkill -f "litellm --config" 2>/dev/null || true
sleep 1
PATH="$REPO_ROOT/.venv-bench/bin:$PATH" \
  BENCH_RUN_ID="$SESSION_ID" \
  BENCH_MASK_AUDIT_SECRET="$MASK_SECRET" \
  nohup bash "$REPO_ROOT/proxy/start_proxy.sh" > /tmp/run_demo06_proxy.log 2>&1 &
trap 'pkill -f "litellm --config" 2>/dev/null || true' EXIT

for i in $(seq 1 30); do
  curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 \
  || { echo "✗ proxy did not become ready (see /tmp/run_demo06_proxy.log)"; exit 1; }
echo "[run_demo06] proxy ready"

# --- drive the two-process refund demo ---------------------------------------
"$BENCH_PY" "$REPO_ROOT/harness/orchestrator/demo_refund_run.py" "$@"
rc=$?

echo "[run_demo06] done → $REPO_ROOT/runs/demo06/summary.{json,csv}"
exit $rc
