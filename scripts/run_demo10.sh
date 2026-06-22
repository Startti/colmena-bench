#!/usr/bin/env bash
# run_demo10.sh — Demo #10 (secure_suspend secret onboarding) one-command driver.
#
# Owns the proxy lifecycle (mirrors scripts/run_demo06.sh): sources .env, derives
# the masking-audit MARKER from scenario_secrets and arms the proxy with it, starts
# the LiteLLM proxy with a stable BENCH_RUN_ID=demo10, waits for readiness, then runs
# the secrets driver across all 6 frameworks and kills the proxy on exit.
#
# The leak/handle counterfactual is audited by the proxy callback scanning request
# bodies for BENCH_MASK_AUDIT_SECRET (== scenario_secrets.MARKER). The header-less
# colmena audit lands in mask-demo10.json (matched by PROXY_BENCH_RUN_ID).
#
# Usage:
#   bash scripts/run_demo10.sh
#   bash scripts/run_demo10.sh --frameworks "colmena crewai"
#
# Requires: setup_all.sh already run; .env with keys + LITELLM_MASTER_KEY +
# COLMENA_DATABASE_URL + SECURE_VALUES_KEY (the last two for the Colmena engine).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env so the driver's subprocess env carries COLMENA_DATABASE_URL +
# SECURE_VALUES_KEY (the Colmena secrets DAG copies COLMENA_DATABASE_URL →
# DATABASE_URL at run_dag time). The 5 competitor runners don't need them.
if [[ -f "$REPO_ROOT/.env" ]]; then set -a; source "$REPO_ROOT/.env"; set +a; fi

BENCH_PY="$REPO_ROOT/.venv-bench/bin/python"
[[ -x "$BENCH_PY" ]] || { echo "✗ .venv-bench missing — run scripts/setup_all.sh"; exit 2; }

SESSION_ID="demo10"

# Derive the audit marker from scenario_secrets and EXPORT it BEFORE starting the
# proxy — the proxy callback reads BENCH_MASK_AUDIT_SECRET from its own env at call
# time, so it must be in this shell's exported env before start_proxy.sh launches.
MARKER=$(PYTHONPATH="$REPO_ROOT/runners/_bench_common" "$BENCH_PY" \
  -c "from bench_common import scenario_secrets as ss; print(ss.MARKER)")
export BENCH_MASK_AUDIT_SECRET="$MARKER"

mkdir -p "$REPO_ROOT/proxy/spans" "$REPO_ROOT/runs/demo10"

echo "[run_demo10] starting proxy (mask audit armed, BENCH_RUN_ID=$SESSION_ID)"
# --- start proxy with the mask-audit secret + a stable BENCH_RUN_ID ----------
pkill -f "litellm --config" 2>/dev/null || true
sleep 1
PATH="$REPO_ROOT/.venv-bench/bin:$PATH" \
  BENCH_RUN_ID="$SESSION_ID" \
  BENCH_MASK_AUDIT_SECRET="$MARKER" \
  nohup bash "$REPO_ROOT/proxy/start_proxy.sh" > /tmp/run_demo10_proxy.log 2>&1 &
trap 'pkill -f "litellm --config" 2>/dev/null || true' EXIT

for i in $(seq 1 30); do
  curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 \
  || { echo "✗ proxy did not become ready (see /tmp/run_demo10_proxy.log)"; exit 1; }
echo "[run_demo10] proxy ready"

# Export PROXY_BENCH_RUN_ID so colmena's header-less masking audit lands in
# mask-demo10.json and the driver finds the session spans file.
export PROXY_BENCH_RUN_ID="$SESSION_ID"

# --- drive the secrets demo --------------------------------------------------
PYTHONPATH="$REPO_ROOT/harness" \
  "$BENCH_PY" -m orchestrator.demo_secrets_run --session-id "$SESSION_ID" "$@"
rc=$?

# Charts (created in Task 7) — guard so this script doesn't fail if absent.
if [[ -f "$REPO_ROOT/harness/orchestrator/demo10_plots.py" ]]; then
  PYTHONPATH="$REPO_ROOT/harness" \
    "$BENCH_PY" -m orchestrator.demo10_plots || true
fi

echo "[run_demo10] done → $REPO_ROOT/runs/demo10/summary.{json,csv}"
exit $rc
