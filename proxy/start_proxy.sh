#!/usr/bin/env bash
# Start the LiteLLM proxy with the bench callback loaded.
#
# Required env (loaded from .env at repo root if present):
#   GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, LITELLM_MASTER_KEY
#
# Optional:
#   LITELLM_PROXY_HOST (default 127.0.0.1)
#   LITELLM_PROXY_PORT (default 4000)
#   BENCH_RUN_ID       (default "adhoc" — span file = proxy/spans/run-adhoc.jsonl)
#
# Usage:
#   ./proxy/start_proxy.sh                       # foreground
#   BENCH_RUN_ID=$(uuidgen) ./proxy/start_proxy.sh   # tag spans for a benchmark run
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env if present (does NOT override values already in the environment).
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${LITELLM_PROXY_HOST:=127.0.0.1}"
: "${LITELLM_PROXY_PORT:=4000}"
: "${LITELLM_SPANS_DIR:=$REPO_ROOT/proxy/spans}"
: "${BENCH_RUN_ID:=adhoc}"

mkdir -p "$LITELLM_SPANS_DIR"

# Make the spans callback importable by name `spans_callback.spans_jsonl`.
# LiteLLM resolves the dotted name in `litellm_settings.callbacks`.
export PYTHONPATH="$REPO_ROOT/proxy${PYTHONPATH:+:$PYTHONPATH}"
export LITELLM_SPANS_DIR
export BENCH_RUN_ID

echo "[proxy] spans → $LITELLM_SPANS_DIR/run-$BENCH_RUN_ID.jsonl"
echo "[proxy] listening on http://$LITELLM_PROXY_HOST:$LITELLM_PROXY_PORT"

exec litellm \
  --config "$REPO_ROOT/proxy/litellm_config.yaml" \
  --host "$LITELLM_PROXY_HOST" \
  --port "$LITELLM_PROXY_PORT"
