#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
export LITELLM_PROXY_API_KEY="$LITELLM_MASTER_KEY"
SESS="demo05_$(date +%s)"
pkill -f litellm 2>/dev/null || true; sleep 1
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID="$SESS" ./proxy/start_proxy.sh > /tmp/proxy_demo05.log 2>&1 &
for i in $(seq 1 45); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health/liveliness 2>/dev/null)" = "200" ] && break; sleep 1; done
runners/colmena/.venv/bin/python harness/orchestrator/demo05_run.py \
  --session-id "$SESS" --out-dir runs/demo05 \
  --frameworks colmena crewai langchain langgraph llamaindex google_adk
pkill -f litellm 2>/dev/null || true
