#!/usr/bin/env bash
# verify_baseline.sh — T11 gate.
#
# Runs Task 1 N=3 against the first two runners that exist (Colmena +
# CrewAI) and validates the four contract invariants from
# `harness/runner_contract.md` §"Pre-flight self-check":
#
#   1. run_output.json validates against run_output.schema.json
#   2. proxy/spans/run-<id>.jsonl exists and has ≥1 line
#   3. sum(span tokens) matches run_output.tokens ±2%
#   4. run_output.tool_calls within ±1 of proxy-counted tool calls
#
# If any check fails, **no further runners ship** until root-caused — see
# IMPLEMENTATION_PLAN.md T11 (GATE).
#
# Requirements:
#   - LiteLLM proxy running (./proxy/start_proxy.sh in another terminal)
#   - .env populated with real API keys (GEMINI_API_KEY, ...)
#   - runners/colmena/ built (`cargo build --release`)
#   - runners/crewai/ installed (`pip install -e runners/crewai`)
#   - Optional: a working `colmena` binary on PATH. Without it the Colmena
#     row reports its failure but the script still grades CrewAI.
#
# Usage:
#   ./scripts/verify_baseline.sh             # N=3 default
#   N=5 ./scripts/verify_baseline.sh

set -euo pipefail
shopt -s nullglob

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${LITELLM_PROXY_BASE_URL:=http://127.0.0.1:4000}"
: "${LITELLM_PROXY_API_KEY:=sk-bench-runner-do-not-use-in-prod}"
: "${LITELLM_SPANS_DIR:=$REPO_ROOT/proxy/spans}"
: "${MODEL_ALIAS:=gemini-2.5-flash}"
: "${N:=3}"
: "${TASK:=$REPO_ROOT/harness/tasks/01_hello_world.yaml}"
# Which runners to gate. Default = the two that landed first (T12 + T13).
# Override e.g. `FRAMEWORKS=crewai` when the colmena binary isn't available.
: "${FRAMEWORKS:=colmena crewai}"

OUT_DIR="$REPO_ROOT/results/verify_baseline-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR" "$LITELLM_SPANS_DIR"

PY="${PYTHON:-python3}"

echo "[verify] N=$N  model=$MODEL_ALIAS  proxy=$LITELLM_PROXY_BASE_URL"
echo "[verify] output dir: $OUT_DIR"

# ---- Pre-flight: proxy reachable -------------------------------------------
if ! curl -fsS -m 2 "$LITELLM_PROXY_BASE_URL/health/readiness" >/dev/null 2>&1 \
   && ! curl -fsS -m 2 "$LITELLM_PROXY_BASE_URL/v1/models" \
        -H "Authorization: Bearer $LITELLM_PROXY_API_KEY" >/dev/null 2>&1; then
  echo "[verify] ✗ proxy not reachable at $LITELLM_PROXY_BASE_URL" >&2
  echo "[verify]   start it with: ./proxy/start_proxy.sh" >&2
  exit 2
fi
echo "[verify] ✓ proxy reachable"

# ---- Run N reps for one framework -------------------------------------------
run_framework() {
  local framework="$1"
  local cmd_prefix=()
  local framework_dir="$REPO_ROOT/runners/$framework"

  case "$framework" in
    colmena)
      local bin="$framework_dir/target/release/colmena-bench-runner"
      [[ -x "$bin" ]] || bin="$framework_dir/target/debug/colmena-bench-runner"
      [[ -x "$bin" ]] || { echo "[verify] ✗ $framework binary not built — cargo build first"; return 1; }
      cmd_prefix=("$bin")
      ;;
    crewai|langchain|langgraph|google_adk|llamaindex)
      cmd_prefix=("$PY" "-m" "runner")
      ;;
    *) echo "[verify] unknown framework: $framework"; return 1 ;;
  esac

  local rep
  local fail=0
  for rep in $(seq 1 "$N"); do
    local run_id
    run_id=$(uuidgen | tr 'A-Z' 'a-z')
    local out_path="$OUT_DIR/$framework/$run_id.json"
    mkdir -p "$(dirname "$out_path")"

    BENCH_RUN_ID="$run_id" \
      LITELLM_PROXY_BASE_URL="$LITELLM_PROXY_BASE_URL" \
      LITELLM_PROXY_API_KEY="$LITELLM_PROXY_API_KEY" \
      PYTHONPATH="$framework_dir:${PYTHONPATH:-}" \
      "${cmd_prefix[@]}" \
        --task "$TASK" \
        --variant default \
        --run-id "$run_id" \
        --model-alias "$MODEL_ALIAS" \
        --proxy-base-url "$LITELLM_PROXY_BASE_URL" \
        --output "$out_path" \
        --timeout-seconds 60 \
        2> "$out_path.stderr" || fail=1
  done
  return $fail
}

# ---- Grader -----------------------------------------------------------------
grade_framework() {
  local framework="$1"
  "$PY" "$REPO_ROOT/scripts/_verify_grader.py" \
    --framework "$framework" \
    --runs-dir "$OUT_DIR/$framework" \
    --spans-dir "$LITELLM_SPANS_DIR"
}

# ---- Drive each framework + grade ------------------------------------------
PASS=()
FAIL=()
SKIP=()

for fw in $FRAMEWORKS; do
  echo
  echo "[verify] ── $fw ──"
  if run_framework "$fw"; then
    echo "[verify] $fw: runner exited 0 on all $N reps"
  else
    echo "[verify] $fw: at least one rep exited non-zero (see stderr files)"
  fi

  if compgen -G "$OUT_DIR/$fw/*.json" >/dev/null; then
    if grade_framework "$fw"; then
      PASS+=("$fw")
    else
      FAIL+=("$fw")
    fi
  else
    echo "[verify] $fw: no run outputs produced — SKIP"
    SKIP+=("$fw")
  fi
done

# ---- Summary ----------------------------------------------------------------
echo
echo "============================================================"
echo " verify_baseline.sh summary  ($OUT_DIR)"
echo "============================================================"
printf "  pass: %s\n" "${PASS[*]:-<none>}"
printf "  fail: %s\n" "${FAIL[*]:-<none>}"
printf "  skip: %s\n" "${SKIP[*]:-<none>}"
echo "============================================================"

[[ ${#FAIL[@]} -eq 0 ]] || exit 1
[[ ${#PASS[@]} -gt 0 ]] || { echo "[verify] no framework even produced output — gate fails"; exit 1; }
echo "[verify] ✓ baseline gate passed"
