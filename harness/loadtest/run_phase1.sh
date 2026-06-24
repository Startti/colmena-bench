#!/usr/bin/env bash
# Phase-1 go/no-go sweep: Colmena Serve + LangGraph warm server vs the mock.
# Calibration is optional; if runs/demo13/calibration.json is absent we use a
# default delay. The sweep itself spends NO tokens.
set -euo pipefail
cd "$(dirname "$0")/../.."

MOCK_PORT=9100
COLMENA_PORT=3000
LANGGRAPH_PORT=9001
DELAY_MS="${DELAY_MS:-}"
CONCURRENCIES="${CONCURRENCIES:-1,2,4,8,16,32,64}"
DURATION_S="${DURATION_S:-30}"
OUT=runs/demo13/phase1
mkdir -p "$OUT"

# 1. delay: from calibration if present, else default 600ms
if [ -z "$DELAY_MS" ]; then
  if [ -f runs/demo13/calibration.json ]; then
    DELAY_MS=$(.venv-bench/bin/python -c "import json;print(int(json.load(open('runs/demo13/calibration.json'))['p50_ms']))")
  else
    DELAY_MS=600
  fi
fi
echo "Using mock delay ${DELAY_MS}ms; concurrencies ${CONCURRENCIES}"

# 2. start mock
.venv-bench/bin/python -m harness.loadtest.stub_llm --port "$MOCK_PORT" --delay-ms "$DELAY_MS" &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null || true' EXIT
sleep 2

# 3. render colmena graph
MOCK_BASE="http://127.0.0.1:${MOCK_PORT}" .venv-bench/bin/python - <<'PY'
import os, pathlib
t = pathlib.Path("harness/loadtest/graphs/loadtest_minimal.json").read_text()
pathlib.Path("/tmp/loadtest_minimal.rendered.json").write_text(t.replace("${MOCK_BASE}", os.environ["MOCK_BASE"]))
PY

# 4. drive each framework (the python runner does start/sample/stop/drive per server)
.venv-bench/bin/python -m harness.loadtest.run_phase1_drive \
  --mock-base "http://127.0.0.1:${MOCK_PORT}" \
  --colmena-port "$COLMENA_PORT" \
  --langgraph-port "$LANGGRAPH_PORT" \
  --concurrencies "$CONCURRENCIES" \
  --duration-s "$DURATION_S" \
  --out "$OUT"

echo "Phase-1 sweep complete -> $OUT"
