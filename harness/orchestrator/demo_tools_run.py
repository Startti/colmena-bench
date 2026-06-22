"""Demo #7 driver — many realistic confusable tools (lazy tool loading).

Sweeps a grid of (config, n_tools, trial) and, per cell, runs ONE runner
subprocess through the live LiteLLM proxy. The generator
(``scenario_tools.generate_toolset``) produces a byte-stable toolset for a given
(n, seed) so every config sees the SAME toolset at a given trial — fairness
across the 7 configs. The needle's whole confusable cluster is always present, so
the model must read the natural-language intent to pick the right tool among
genuinely similar ones.

CONFIGS = 7: colmena-lazy / colmena-eager (same framework, BENCH_COLMENA_LAZY
1/0) + the 5 competitors.

TOKEN MEASUREMENT (the critical bit):
  Colmena's engine LLM calls do NOT forward the ``x-bench-run-id`` header, so all
  of its spans land in the proxy's single SESSION file
  ``proxy/spans/run-<PROXY_BENCH_RUN_ID>.jsonl`` (NOT per ``--run-id``). The
  competitors ARE header-capable, so their spans land in
  ``proxy/spans/run-<run_id>.jsonl``.

  Because the driver runs cells SEQUENTIALLY, colmena tokens are measured by DELTA
  on the session file: record its line count BEFORE the subprocess, then sum
  ``tokens_input`` over the lines appended AFTER. Competitor tokens are the full
  sum over ``run-<run_id>.jsonl``.

Outputs ``runs/demo07/summary.{json,csv}`` (one row per (config, count), means
over trials) and prints one progress line per cell.

Driven by ``scripts/run_demo07.sh`` (which owns the proxy lifecycle and sets the
proxy's BENCH_RUN_ID=demo07; pass it here via env ``PROXY_BENCH_RUN_ID``).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR / "orchestrator"))
sys.path.insert(0, str(HARNESS_DIR))
sys.path.insert(0, str(REPO_ROOT / "runners" / "_bench_common"))

from orchestrator.full_run import venv_python, _proxy_key  # noqa: E402
from bench_common import scenario_tools  # noqa: E402

DEFAULT_COUNTS = [5, 10, 20]
DEFAULT_TRIALS = 5

# The 7 configs. colmena-lazy/eager are the SAME framework (colmena) toggled via
# BENCH_COLMENA_LAZY; the 5 competitors have no such toggle.
CONFIGS: list[dict[str, Any]] = [
    {"name": "colmena-lazy", "framework": "colmena", "lazy": "1"},
    {"name": "colmena-eager", "framework": "colmena", "lazy": "0"},
    {"name": "crewai", "framework": "crewai"},
    {"name": "langchain", "framework": "langchain"},
    {"name": "langgraph", "framework": "langgraph"},
    {"name": "llamaindex", "framework": "llamaindex"},
    {"name": "google_adk", "framework": "google_adk"},
]

TASK_PATH = REPO_ROOT / "harness" / "tasks" / "07_tools.yaml"


def line_count(path: "str | Path") -> int:
    """Number of non-empty JSONL lines in `path` (0 if missing)."""
    p = Path(path)
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if line.strip())


def sum_tokens_from_offset(path: "str | Path", offset_lines: int) -> int:
    """Sum `tokens_input` over the JSONL lines AFTER `offset_lines` (0 if missing).

    Only non-empty lines are counted, consistent with `line_count`.
    """
    p = Path(path)
    if not p.exists():
        return 0
    lines = [line for line in p.read_text().splitlines() if line.strip()]
    total = 0
    for line in lines[offset_lines:]:
        try:
            total += int(json.loads(line).get("tokens_input", 0) or 0)
        except (ValueError, json.JSONDecodeError):
            continue
    return total


def _extract_answer(out_data: dict) -> str:
    """Pull the answer string out of the emitted runner output JSON.

    Handlers return ``({"answer": text}, usage, extras)`` so core serializes
    ``answer`` as ``{"answer": text}``; but some handlers may emit the bare
    string. Handle both robustly.
    """
    ans = out_data.get("answer")
    if isinstance(ans, dict):
        inner = ans.get("answer", ans)
        return inner if isinstance(inner, str) else json.dumps(inner)
    if ans is None:
        return ""
    return ans if isinstance(ans, str) else json.dumps(ans)


def _env_for(cfg: dict, run_id: str, proxy_base_url: str,
             toolset_path: Path, toolcall_log: Path) -> dict[str, str]:
    fw = cfg["framework"]
    env = os.environ.copy()
    env.update({
        "BENCH_RUN_ID": run_id,
        "BENCH_TOOLSET_PATH": str(toolset_path),
        "BENCH_TOOLCALL_LOG": str(toolcall_log),
        "LITELLM_PROXY_BASE_URL": proxy_base_url,
        "LITELLM_PROXY_API_KEY": _proxy_key(),
        "PYTHONPATH": f"{REPO_ROOT/'runners'/fw}:{REPO_ROOT/'runners'/'_bench_common'}",
    })
    if fw == "colmena":
        env["BENCH_COLMENA_LAZY"] = cfg.get("lazy", "1")
    return env


def _run_cell(cfg: dict, count: int, trial: int,
              model_alias: str, proxy_base_url: str, timeout: int,
              raw_dir: Path, spans_dir: Path, session_file: Path) -> dict[str, Any]:
    """Run one (config, count, trial) cell; return a per-trial record."""
    fw = cfg["framework"]
    name = cfg["name"]
    run_id = f"d7-{name}-n{count}-t{trial}"

    spec = scenario_tools.generate_toolset(count, seed=trial)
    toolset_path = raw_dir / f"{run_id}.toolset.json"
    toolset_path.write_text(json.dumps(spec))
    toolcall_log = raw_dir / f"{run_id}.toolcalls.jsonl"
    if toolcall_log.exists():
        toolcall_log.unlink()
    out_path = raw_dir / f"{run_id}.json"

    py = venv_python(fw)
    rec: dict[str, Any] = {
        "config": name, "framework": fw, "count": count,
        "trial": trial, "run_id": run_id,
    }
    if not py.exists():
        return {**rec, "hard_error": True, "error": "no venv",
                "selection_ok": False, "arg_ok": False, "answer_ok": False,
                "wrong_tool_called": False, "tokens_in": 0}

    cmd = [
        str(py), "-m", "runner", "--task", str(TASK_PATH),
        "--variant", f"n{count}", "--run-id", run_id,
        "--model-alias", model_alias, "--proxy-base-url", proxy_base_url,
        "--output", str(out_path), "--timeout-seconds", str(timeout),
    ]
    env = _env_for(cfg, run_id, proxy_base_url, toolset_path, toolcall_log)

    # Colmena spans land in the proxy SESSION file (header-less); measure by delta.
    pre = line_count(session_file) if fw == "colmena" else 0

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout + 60)
        returncode = proc.returncode
        stderr = proc.stderr
    except subprocess.TimeoutExpired as e:
        returncode = -1
        stderr = f"TimeoutExpired: {e}"

    out_data: dict = {}
    if out_path.exists():
        try:
            out_data = json.loads(out_path.read_text())
        except json.JSONDecodeError:
            out_data = {}

    extras = out_data.get("extras") or {}
    runner_error = out_data.get("error")
    hard_error = (returncode != 0) or bool(extras.get("error")) or bool(runner_error)

    # Tokens: colmena via session-file delta, competitors via per-run-id file.
    if fw == "colmena":
        tokens_in = sum_tokens_from_offset(session_file, pre)
    else:
        tokens_in = sum_tokens_from_offset(spans_dir / f"run-{run_id}.jsonl", 0)

    answer = _extract_answer(out_data)
    calls = scenario_tools.read_tool_calls(toolcall_log)
    sc = scenario_tools.score(spec, calls, answer)

    if hard_error:
        (raw_dir / f"{run_id}.stderr").write_text(stderr or "")

    return {
        **rec,
        "hard_error": hard_error,
        "error": runner_error or (None if returncode == 0 else f"exit {returncode}"),
        "tokens_in": tokens_in,
        "selection_ok": sc["selection_ok"],
        "arg_ok": sc["arg_ok"],
        "answer_ok": sc["answer_ok"],
        "wrong_tool_called": sc["wrong_tool_called"],
    }


def _aggregate(records: list[dict]) -> list[dict]:
    """Mean per (config, count) over trials."""
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        groups.setdefault((r["config"], r["count"]), []).append(r)
    rows: list[dict] = []
    for (config, count), recs in groups.items():
        n = len(recs)
        rows.append({
            "config": config,
            "framework": recs[0]["framework"],
            "n_tools": count,
            "trials": n,
            "selection_acc": mean(1.0 if r["selection_ok"] else 0.0 for r in recs),
            "arg_acc": mean(1.0 if r["arg_ok"] else 0.0 for r in recs),
            "answer_acc": mean(1.0 if r["answer_ok"] else 0.0 for r in recs),
            "wrong_tool_rate": mean(1.0 if r.get("wrong_tool_called") else 0.0 for r in recs),
            "tokens_in_mean": mean(r["tokens_in"] for r in recs),
            "hard_error_rate": mean(1.0 if r["hard_error"] else 0.0 for r in recs),
        })
    rows.sort(key=lambda r: (r["n_tools"], r["config"]))
    return rows


def _write_outputs(rows: list[dict], runs_dir: Path) -> tuple[Path, Path]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_path = runs_dir / "summary.json"
    csv_path = runs_dir / "summary.csv"
    json_path.write_text(json.dumps(rows, indent=2, default=str))
    cols = ["config", "framework", "n_tools", "trials",
            "selection_acc", "arg_acc", "answer_acc", "wrong_tool_rate",
            "tokens_in_mean", "hard_error_rate"]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})
    return json_path, csv_path


def _print_summary(rows: list[dict]) -> None:
    print("\n=== Demo #7 — many-tools sweep summary ===")
    hdr = (f"{'config':<14} {'n':>4} {'sel':>5} {'arg':>5} {'ans':>5} "
           f"{'wrong':>6} {'tokens_in':>10} {'hard_err':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['config']:<14} {r['n_tools']:>4} "
              f"{r['selection_acc']:>5.2f} {r['arg_acc']:>5.2f} "
              f"{r['answer_acc']:>5.2f} {r['wrong_tool_rate']:>6.2f} "
              f"{r['tokens_in_mean']:>10.0f} {r['hard_error_rate']:>8.2f}")


def _parse_list(s: str | None, cast, default):
    if not s:
        return default
    return [cast(x.strip()) for x in s.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Demo #7 — many-tools sweep driver")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--counts", default=None, help="comma list, e.g. 5,10,20")
    p.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    p.add_argument("--configs", default=None, help="comma list of config names")
    p.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "runs" / "demo07" / "raw")
    p.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs" / "demo07")
    p.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy" / "spans")
    args = p.parse_args(argv)

    counts = _parse_list(args.counts, int, DEFAULT_COUNTS)
    trials = args.trials
    wanted = _parse_list(args.configs, str, None)
    configs = [c for c in CONFIGS if (wanted is None or c["name"] in wanted)]

    proxy_run_id = os.environ.get("PROXY_BENCH_RUN_ID", "demo07")
    session_file = args.spans_dir / f"run-{proxy_run_id}.jsonl"

    import yaml
    task_def = yaml.safe_load(TASK_PATH.read_text())
    timeout = int(task_def.get("timeout_seconds", 120))

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.spans_dir.mkdir(parents=True, exist_ok=True)

    total = len(configs) * len(counts) * trials
    print(f"[demo07] grid: {len(configs)} configs x {counts} "
          f"x {trials} trials = {total} runs")
    print(f"[demo07] colmena session file: {session_file}")

    records: list[dict] = []
    i = 0
    for cfg in configs:
        for count in counts:
            for trial in range(trials):
                i += 1
                rec = _run_cell(cfg, count, trial,
                                args.model_alias, args.proxy_base_url, timeout,
                                args.raw_dir, args.spans_dir, session_file)
                records.append(rec)
                print(f"[{i}/{total}] {rec['config']:<14} n={count:<4} "
                      f"sel={int(rec['selection_ok'])} "
                      f"arg={int(rec['arg_ok'])} ans={int(rec['answer_ok'])} "
                      f"wrong={int(rec.get('wrong_tool_called', False))} "
                      f"tok={rec['tokens_in']:<7} "
                      f"{'HARD_ERR' if rec['hard_error'] else 'ok'}"
                      + (f" :: {rec['error']}" if rec.get('error') else ""))

    rows = _aggregate(records)
    json_path, csv_path = _write_outputs(rows, args.runs_dir)
    # Also persist the raw per-trial records for debugging / charts.
    (args.runs_dir / "records.json").write_text(json.dumps(records, indent=2, default=str))
    _print_summary(rows)
    print(f"\nwrote {json_path}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
