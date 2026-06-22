#!/usr/bin/env bash
# Task 4 (CSV analytical) across all 6 frameworks: naive (CSV in prompt) vs
# expert (SQL tool), over variants S/M/L. Each run_task.sh call owns its proxy +
# writes results/<date>-task<id>/. Expert is cheap (N=3); naive is expensive
# (whole CSV in context) so N=1; naive L (~1M tokens) demonstrates the break.
set -uo pipefail
cd "$(dirname "$0")/.."

run() {  # task_id variant n
  echo "==================== $1 variant=$2 N=$3 ===================="
  bash scripts/run_task.sh "$1" --variant "$2" --n "$3" || echo "[warn] $1/$2 returned nonzero"
}

for v in S M L; do run 04_csv_expert "$v" 3; done
for v in S M L; do run 04_csv_naive  "$v" 1; done

echo "TASK4_ALL_DONE"
echo "results dirs:"; ls -dt results/*-task04_* 2>/dev/null | head -12
