#!/usr/bin/env bash
# run_task.sh — run one task across all 6 frameworks and produce a comparative
# report. Owns the proxy lifecycle (starts it tagged with a session id so
# Colmena's header-less spans correlate).
#
# Usage:
#   bash scripts/run_task.sh 01                      # N=30, all frameworks
#   bash scripts/run_task.sh 01 --n 5                # quick
#   bash scripts/run_task.sh 01 --n 10 --frameworks "colmena crewai"
#
# Requires: setup_all.sh already run; .env with keys + LITELLM_MASTER_KEY.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TASK_NUM="${1:?usage: run_task.sh <task-number> [--n N] [--frameworks \"...\"]}"
shift || true

N=30
FRAMEWORKS=""
VARIANT="default"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --n) N="$2"; shift 2 ;;
    --frameworks) FRAMEWORKS="$2"; shift 2 ;;
    --variant) VARIANT="$2"; shift 2 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

# Resolve the task yaml (01 → harness/tasks/01_*.yaml).
TASK_PATH=$(ls "$REPO_ROOT"/harness/tasks/"${TASK_NUM}"_*.yaml 2>/dev/null | head -1)
[[ -f "$TASK_PATH" ]] || { echo "✗ no task yaml for '$TASK_NUM' in harness/tasks/"; exit 2; }

BENCH_PY="$REPO_ROOT/.venv-bench/bin/python"
[[ -x "$BENCH_PY" ]] || { echo "✗ .venv-bench missing — run scripts/setup_all.sh"; exit 2; }

DATE=$(date +%Y%m%d-%H%M%S)
SESSION_ID="task${TASK_NUM}-${DATE}"
OUT_DIR="$REPO_ROOT/results/${DATE}-task${TASK_NUM}"
mkdir -p "$OUT_DIR" "$REPO_ROOT/proxy/spans"
rm -f "$REPO_ROOT/proxy/spans/run-${SESSION_ID}.jsonl"

echo "[run_task] task=$TASK_PATH  N=$N  session=$SESSION_ID"

# --- start proxy tagged with the session id (for colmena's header-less spans) ---
pkill -f "litellm --config" 2>/dev/null || true
sleep 1
PATH="$REPO_ROOT/.venv-bench/bin:$PATH" BENCH_RUN_ID="$SESSION_ID" \
  nohup bash "$REPO_ROOT/proxy/start_proxy.sh" > /tmp/run_task_proxy.log 2>&1 &
trap 'pkill -f "litellm --config" 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  curl -fsS -m 2 http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break
  sleep 1
done
echo "[run_task] proxy ready"

# --- drive the orchestrator ---
EXTRA=()
[[ -n "$FRAMEWORKS" ]] && EXTRA=(--frameworks $FRAMEWORKS)
"$BENCH_PY" "$REPO_ROOT/harness/orchestrator/full_run.py" \
  --task "$TASK_PATH" \
  --n "$N" \
  --variant "$VARIANT" \
  --session-id "$SESSION_ID" \
  --out-dir "$OUT_DIR" \
  ${EXTRA[@]+"${EXTRA[@]}"}

echo "[run_task] done → $OUT_DIR/report/report.md"
