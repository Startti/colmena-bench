#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
RID="smoke05colmena"
# Start a dedicated proxy for this smoke (Colmena spans route by the proxy's BENCH_RUN_ID).
pkill -f litellm 2>/dev/null || true; sleep 1
PATH="$PWD/.venv-bench/bin:$PATH" BENCH_RUN_ID="$RID" ./proxy/start_proxy.sh > /tmp/proxy_smoke05colmena.log 2>&1 &
for i in $(seq 1 45); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/health/liveliness 2>/dev/null)" = "200" ] && break
  sleep 1
done
export LITELLM_PROXY_API_KEY="$LITELLM_MASTER_KEY"
PYTHONPATH="runners/colmena:runners/_bench_common" \
  runners/colmena/.venv/bin/python -m runner \
  --task harness/tasks/05_context_scrubbing.yaml --variant default \
  --run-id "$RID" --model-alias gemini-2.5-flash \
  --proxy-base-url http://127.0.0.1:4000 \
  --output /tmp/demo05_colmena.json --timeout-seconds 300
pkill -f litellm 2>/dev/null || true
runners/colmena/.venv/bin/python - <<'PY'
import json
d = json.load(open('/tmp/demo05_colmena.json'))
assert d.get('error') is None, d.get('error')
ans = d['answer']; b = d['extras']['turn_boundaries']
assert isinstance(ans, list) and len(ans) == 10, f"answers={ans!r}"
assert len(b) == 11, f"boundaries={len(b)}"
print("OK turns=", len(ans), "boundaries=", len(b))
print("sample answer[0][:120]=", str(ans[0])[:120])
PY
echo "--- spans (input tokens should NOT explode on chart turns) ---"
grep -c . proxy/spans/run-smoke05colmena.jsonl
