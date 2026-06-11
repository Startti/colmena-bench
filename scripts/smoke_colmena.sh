#!/usr/bin/env bash
# smoke_colmena.sh — end-to-end proof that the Colmena runner routes its LLM
# call through the proxy and the token span is captured.
#
# Colmena's OpenAI adapter can't forward a custom `x-bench-run-id` header
# (unlike the Python framework runners), so per-run span correlation here
# uses a dedicated proxy started with BENCH_RUN_ID == this run's id. The
# script owns the proxy lifecycle so it's fully self-contained.
#
# Requirements:
#   - .env with real keys + LITELLM_MASTER_KEY (== LITELLM_PROXY_API_KEY)
#   - .venv-bench with litellm + the colmena module (maturin develop)
#
# Usage: bash scripts/smoke_colmena.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv-bench"
PY="$VENV/bin/python"
[[ -x "$PY" ]] || { echo "✗ .venv-bench not found — create it first"; exit 2; }

RUN_ID="colmena-smoke-$(date +%s)"
OUT_DIR="$REPO_ROOT/results/smoke_colmena-$RUN_ID"
mkdir -p "$OUT_DIR" "$REPO_ROOT/proxy/spans"
SPAN_FILE="$REPO_ROOT/proxy/spans/run-$RUN_ID.jsonl"
rm -f "$SPAN_FILE"

echo "[smoke] run_id=$RUN_ID"

# --- start a dedicated proxy tagged with this run id ---
pkill -f "litellm --config" 2>/dev/null || true
sleep 1
PATH="$VENV/bin:$PATH" BENCH_RUN_ID="$RUN_ID" \
  nohup bash "$REPO_ROOT/proxy/start_proxy.sh" > /tmp/smoke_colmena_proxy.log 2>&1 &
PROXY_STARTED=1
cleanup() { [[ "${PROXY_STARTED:-0}" == "1" ]] && pkill -f "litellm --config" 2>/dev/null || true; }
trap cleanup EXIT

for i in $(seq 1 25); do
  curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break
  sleep 1
done
echo "[smoke] proxy ready"

# --- run the Colmena runner ---
out_path="$OUT_DIR/$RUN_ID.json"
set +e
BENCH_RUN_ID="$RUN_ID" \
  LITELLM_PROXY_API_KEY="$(grep -E '^LITELLM_MASTER_KEY=' .env | cut -d= -f2-)" \
  PYTHONPATH="$REPO_ROOT/runners/colmena:$REPO_ROOT/runners/_bench_common" \
  "$PY" -m runner \
    --task "$REPO_ROOT/harness/tasks/01_hello_world.yaml" \
    --variant default \
    --run-id "$RUN_ID" \
    --model-alias gemini-2.5-flash \
    --proxy-base-url http://127.0.0.1:4000 \
    --output "$out_path" \
    --timeout-seconds 60 \
    2> "$out_path.stderr"
rc=$?
set -e

echo "[smoke] runner exit=$rc"

# --- grade ---
"$PY" "$REPO_ROOT/scripts/_verify_grader.py" \
  --framework colmena \
  --runs-dir "$OUT_DIR" \
  --spans-dir "$REPO_ROOT/proxy/spans"
grade_rc=$?

echo "=== run output ==="
"$PY" -c "import json; d=json.load(open('$out_path')); print('answer:', repr(d['answer'])[:60]); print('success:', d['success']); print('framework_version:', d['framework_version'])" || cat "$out_path.stderr"
echo "=== proxy span ==="
if [[ -f "$SPAN_FILE" ]]; then
  "$PY" -c "import json; [print(json.dumps({k:s[k] for k in ('run_id','provider_model','tokens_input','tokens_output','ok')})) for s in map(json.loads, open('$SPAN_FILE'))]"
else
  echo "✗ no span file at $SPAN_FILE"
  exit 1
fi

[[ $grade_rc -eq 0 ]] && echo "[smoke] ✓ colmena routes through proxy, span captured" || { echo "[smoke] ✗ grade failed"; exit 1; }
