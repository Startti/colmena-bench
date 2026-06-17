#!/usr/bin/env bash
# Run the full 6-framework context-tax demo N times, each pass with its OWN proxy
# session + out-dir, so per-pass Colmena spans never collide (Colmena routes spans
# by the proxy's BENCH_RUN_ID, fixed at proxy start). Aggregate across passes with
# harness/orchestrator/demo05_aggregate_n.py. Default N=12.
#
# Usage: bash scripts/run_demo05_n.sh [N]
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
export LITELLM_PROXY_API_KEY="$LITELLM_MASTER_KEY"

N="${1:-12}"
BASE="runs/demo05/n${N}"
mkdir -p "$BASE"
echo "[n-run] N=$N → $BASE"

for i in $(seq 1 "$N"); do
  SESS="demo05n_$(date +%s)_${i}"
  OUT="$BASE/run_${i}"
  echo "[n-run] === pass $i/$N  sess=$SESS ==="
  pkill -f litellm 2>/dev/null || true; sleep 1
  PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID="$SESS" ./proxy/start_proxy.sh > "/tmp/proxy_n_${i}.log" 2>&1 &
  up=0
  for _ in $(seq 1 45); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health/liveliness 2>/dev/null)" = "200" ] && { up=1; break; }
    sleep 1
  done
  if [ "$up" != "1" ]; then echo "[n-run] pass $i: proxy did not come up, skipping"; pkill -f litellm 2>/dev/null || true; continue; fi
  runners/colmena/.venv/bin/python harness/orchestrator/demo05_run.py \
    --session-id "$SESS" --out-dir "$OUT" \
    --frameworks colmena crewai langchain langgraph llamaindex google_adk \
    > "/tmp/orch_n_${i}.log" 2>&1
  echo "[n-run] pass $i done (exit $?); report → $OUT/report/chart_data.json"
  pkill -f litellm 2>/dev/null || true
done
echo "[n-run] ALL $N passes complete."
