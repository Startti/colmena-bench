#!/usr/bin/env bash
# setup_all.sh — create every venv the benchmark needs, with pinned deps.
#
# Layout (all gitignored):
#   .venv-bench                 → the LiteLLM proxy (litellm[proxy])
#   runners/<framework>/.venv   → one isolated venv per runner, pinned versions
#
# Idempotent: existing venvs are reused unless --force is passed.
#
# Requirements: uv (https://docs.astral.sh/uv/), Python 3.11 available to uv,
# and — for the Colmena runner — a local checkout of Startti/colmena with the
# base_url patch (develop) so `maturin develop` can build the native module.
#
# Usage:
#   bash scripts/setup_all.sh                # all venvs, skip existing
#   bash scripts/setup_all.sh --force        # rebuild every venv
#   COLMENA_REPO=/path/to/colmena bash scripts/setup_all.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

: "${COLMENA_REPO:=/Users/danielgarcia/startti/colmena}"
PYVER=3.11

command -v uv >/dev/null || { echo "✗ uv not found — install from https://docs.astral.sh/uv/"; exit 2; }

# Common deps every runner needs (bench_common core + grader).
COMMON_DEPS=(pyyaml psutil jsonschema)

# framework → pinned package specs (space-separated). Colmena is special.
fw_deps() {
  case "$1" in
    crewai)     echo "crewai==1.14.6 litellm==1.88.1" ;;
    langchain)  echo "langchain==1.3.6 langchain-openai langchain-experimental==0.4.2 pandas tabulate" ;;
    langgraph)  echo "langgraph==1.2.4 langchain-openai" ;;
    llamaindex) echo "llama-index-core==0.14.22 llama-index-llms-openai-like llama-index-experimental==0.6.6 pandas polars" ;;
    google_adk) echo "google-adk==2.2.0 litellm==1.88.1" ;;
    *) echo "" ;;
  esac
}

make_venv() {
  local dir="$1"
  if [[ -d "$dir" && "$FORCE" == "0" ]]; then
    echo "  [skip] $dir exists (use --force to rebuild)"
    return 1
  fi
  [[ "$FORCE" == "1" ]] && rm -rf "$dir"
  uv venv --python "$PYVER" "$dir" >/dev/null 2>&1
  return 0
}

echo "==> proxy venv (.venv-bench)"
if make_venv "$REPO_ROOT/.venv-bench"; then
  VIRTUAL_ENV="$REPO_ROOT/.venv-bench" uv pip install -q \
    "litellm[proxy]==1.88.1" "${COMMON_DEPS[@]}" pytest
  echo "  installed litellm[proxy]==1.88.1"
fi

for fw in crewai langchain langgraph llamaindex google_adk; do
  echo "==> runner venv: $fw"
  dir="$REPO_ROOT/runners/$fw/.venv"
  if make_venv "$dir"; then
    # shellcheck disable=SC2046
    VIRTUAL_ENV="$dir" uv pip install -q $(fw_deps "$fw") "${COMMON_DEPS[@]}"
    echo "  installed: $(fw_deps "$fw")"
  fi
done

echo "==> runner venv: colmena (native module via maturin)"
dir="$REPO_ROOT/runners/colmena/.venv"
if make_venv "$dir"; then
  VIRTUAL_ENV="$dir" uv pip install -q "${COMMON_DEPS[@]}" "maturin>=1,<2"
  if [[ -d "$COLMENA_REPO" ]]; then
    ( cd "$COLMENA_REPO" && VIRTUAL_ENV="$dir" "$dir/bin/maturin" develop --release \
        --manifest-path src/libs/colmena/Cargo.toml >/dev/null 2>&1 ) \
      && echo "  built colmena module from $COLMENA_REPO" \
      || echo "  ⚠ maturin build failed — check $COLMENA_REPO (need develop + base_url patch)"
  else
    echo "  ⚠ COLMENA_REPO not found at $COLMENA_REPO — skipped colmena module build"
  fi
fi
# attachment_run_python runs pandas/numpy/scipy inside the colmena venv's embedded
# CPython (pyo3); without these the tool fails with 'No module named pandas'.
# Install unconditionally (idempotent) so a --force rebuild and a fresh venv both work.
VIRTUAL_ENV="$dir" uv pip install -q --python "$dir/bin/python" pandas numpy scipy \
  && echo "  installed pandas numpy scipy into colmena venv (required by attachment_run_python)" \
  || echo "  ⚠ pandas/numpy/scipy install failed — attachment_run_python will not work"

echo
echo "✓ setup complete. Venvs:"
echo "    proxy:   .venv-bench"
for fw in crewai colmena langchain langgraph llamaindex google_adk; do
  py="$REPO_ROOT/runners/$fw/.venv/bin/python"
  [[ -x "$py" ]] && echo "    $fw: runners/$fw/.venv" || echo "    $fw: (missing)"
done
echo
echo "Next: start the proxy (./proxy/start_proxy.sh) then run a task:"
echo "    bash scripts/run_task.sh 01 --n 30"
