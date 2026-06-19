"""Demo #7 v2 — multi-turn SESSION driver (lazy tool loading across a conversation).

Models a realistic ~30-tool agent over a 10-turn conversation. For each
(config, seed) it generates a byte-stable session
(``scenario_tools.generate_session(30, 10, seed)``) so every config replays the
SAME toolset + per-turn requests at a given seed — fairness across the 7 configs.

Per turn the hero metric is CUMULATIVE input tokens: colmena-lazy sends a catalog
once and pulls schemas on demand, while every other config (incl. colmena-eager,
lazy OFF) re-sends all ~30 tool schemas every turn. The gap widens with turns.

TOKEN MEASUREMENT (same trick as ``demo_tools_run``):
  Colmena's engine LLM calls do NOT forward the ``x-bench-run-id`` header, so all
  of its spans land in the single SESSION file
  ``proxy/spans/run-<PROXY_BENCH_RUN_ID>.jsonl``. Because cells run SEQUENTIALLY,
  colmena's spans for a run are the lines appended AFTER its pre-run line count.
  Competitors forward the header, so their spans land in
  ``proxy/spans/run-<run_id>.jsonl``.

Spans are bucketed into turns by wall-clock via the runner-emitted
``extras.turn_boundaries`` (11 ISO timestamps for 10 turns) using
``demo05_buckets.bucket_spans_by_turn``.

Outputs ``runs/demo07/session_summary.{json,csv}`` (one row per (config, turn),
means over seeds) and prints a per-config cumulative-at-turn-9 line.

Driven small for validation; the human launches the full 7x5 sweep.
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
from orchestrator.demo05_buckets import bucket_spans_by_turn, _to_epoch  # noqa: E402
from bench_common import scenario_tools  # noqa: E402

N_TOOLS = 30
N_TURNS = 10
SEEDS = range(5)
PROXY_BENCH_RUN_ID = os.environ.get("PROXY_BENCH_RUN_ID", "demo07")

# The 7 configs. colmena-lazy/eager are the SAME framework toggled via
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

TASK_PATH = REPO_ROOT / "harness" / "tasks" / "07b_tools_session.yaml"


def line_count(path: "str | Path") -> int:
    """Number of non-empty JSONL lines in `path` (0 if missing)."""
    p = Path(path)
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if line.strip())


def load_spans_from_offset(path: "str | Path", offset_lines: int) -> list[dict]:
    """Parse JSONL span dicts AFTER `offset_lines` (empty list if missing)."""
    p = Path(path)
    if not p.exists():
        return []
    lines = [line for line in p.read_text().splitlines() if line.strip()]
    spans: list[dict] = []
    for line in lines[offset_lines:]:
        try:
            spans.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return spans


def calls_by_turn(calls: list[dict], boundaries: list[str]) -> list[list[dict]]:
    """Bucket tool calls into turns by their epoch `ts`.

    boundaries has length n_turns + 1: turn k = [edges[k], edges[k+1]). A call
    at/after the last boundary lands in the last turn (final-emit clock skew).
    """
    edges = [_to_epoch(b) for b in boundaries]
    n_turns = max(0, len(edges) - 1)
    buckets: list[list[dict]] = [[] for _ in range(n_turns)]
    if n_turns == 0:
        return buckets
    for c in calls:
        t = float(c.get("ts", 0))
        idx = 0
        while idx < n_turns - 1 and t >= edges[idx + 1]:
            idx += 1
        buckets[idx].append(c)
    return buckets


def _env_for(cfg: dict, run_id: str, proxy_base_url: str,
             session_path: Path, toolcall_log: Path) -> dict[str, str]:
    fw = cfg["framework"]
    env = os.environ.copy()
    env.update({
        "BENCH_RUN_ID": run_id,
        "BENCH_SESSION_PATH": str(session_path),
        "BENCH_TOOLCALL_LOG": str(toolcall_log),
        "LITELLM_PROXY_BASE_URL": proxy_base_url,
        "LITELLM_PROXY_API_KEY": _proxy_key(),
        "PYTHONPATH": f"{REPO_ROOT/'runners'/fw}:{REPO_ROOT/'runners'/'_bench_common'}",
    })
    if fw == "colmena":
        env["BENCH_COLMENA_LAZY"] = cfg.get("lazy", "1")
    return env


def _run_cell(cfg: dict, seed: int, model_alias: str, proxy_base_url: str,
              timeout: int, raw_dir: Path, session_raw_dir: Path,
              spans_dir: Path, session_file: Path) -> dict[str, Any]:
    """Run one (config, seed) session; return a per-run record with per-turn rows."""
    fw = cfg["framework"]
    name = cfg["name"]
    run_id = f"d7s-{name}-s{seed}"

    spec = scenario_tools.generate_session(N_TOOLS, N_TURNS, seed)
    session_path = session_raw_dir / f"{run_id}.session.json"
    session_path.write_text(json.dumps(spec))
    toolcall_log = raw_dir / f"{run_id}.toolcalls.jsonl"
    if toolcall_log.exists():
        toolcall_log.unlink()
    out_path = raw_dir / f"{run_id}.json"

    py = venv_python(fw)
    base = {"config": name, "framework": fw, "seed": seed, "run_id": run_id}
    if not py.exists():
        return {**base, "hard_error": True, "error": "no venv", "turns": []}

    cmd = [
        str(py), "-m", "runner", "--task", str(TASK_PATH),
        "--variant", "default", "--run-id", run_id,
        "--model-alias", model_alias, "--proxy-base-url", proxy_base_url,
        "--output", str(out_path), "--timeout-seconds", str(timeout),
    ]
    env = _env_for(cfg, run_id, proxy_base_url, session_path, toolcall_log)

    # Colmena spans land in the proxy SESSION file (header-less); measure by delta.
    pre = line_count(session_file) if fw == "colmena" else 0

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout + 120)
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
    boundaries = extras.get("turn_boundaries") or []

    if hard_error and stderr:
        (raw_dir / f"{run_id}.stderr").write_text(stderr)

    if not boundaries or len(boundaries) < 2:
        return {**base, "hard_error": True,
                "error": runner_error or f"no turn_boundaries (exit {returncode})",
                "turns": []}

    # Load this run's spans and bucket into turns.
    if fw == "colmena":
        spans = load_spans_from_offset(session_file, pre)
    else:
        spans = load_spans_from_offset(spans_dir / f"run-{run_id}.jsonl", 0)
    bucketed = bucket_spans_by_turn(spans, boundaries)
    per_turn_in = bucketed["per_turn_input"]
    cum_in = bucketed["cumulative_input"]

    # Score per turn from the tool-call log.
    calls = scenario_tools.read_tool_calls(toolcall_log)
    by_turn = calls_by_turn(calls, boundaries)

    n_turns = len(spec["turns"])
    turn_rows: list[dict] = []
    for i in range(n_turns):
        sc = scenario_tools.score_turn(spec, i, by_turn[i] if i < len(by_turn) else [], "")
        turn_rows.append({
            "turn": i,
            "per_turn_tokens": per_turn_in[i] if i < len(per_turn_in) else 0,
            "cum_tokens": cum_in[i] if i < len(cum_in) else 0,
            "selection_ok": bool(sc["selection_ok"]),
            "arg_ok": bool(sc["arg_ok"]),
            "wrong_tool_called": bool(sc["wrong_tool_called"]),
        })

    return {**base, "hard_error": hard_error,
            "error": runner_error or (None if returncode == 0 else f"exit {returncode}"),
            "turns": turn_rows}


def _aggregate(records: list[dict]) -> list[dict]:
    """Mean per (config, turn) over seeds. Skips hard-errored runs."""
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        if r.get("hard_error") or not r.get("turns"):
            continue
        for t in r["turns"]:
            groups.setdefault((r["config"], t["turn"]), []).append(t)
    rows: list[dict] = []
    for (config, turn), turns in groups.items():
        rows.append({
            "config": config,
            "turn": turn,
            "cum_tokens_mean": mean(t["cum_tokens"] for t in turns),
            "per_turn_tokens_mean": mean(t["per_turn_tokens"] for t in turns),
            "selection_acc": mean(1.0 if t["selection_ok"] else 0.0 for t in turns),
            "arg_acc": mean(1.0 if t["arg_ok"] else 0.0 for t in turns),
            "seeds": len(turns),
        })
    rows.sort(key=lambda r: (r["config"], r["turn"]))
    return rows


def _write_outputs(rows: list[dict], runs_dir: Path) -> tuple[Path, Path]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_path = runs_dir / "session_summary.json"
    csv_path = runs_dir / "session_summary.csv"
    json_path.write_text(json.dumps(rows, indent=2, default=str))
    cols = ["config", "turn", "cum_tokens_mean", "per_turn_tokens_mean",
            "selection_acc", "arg_acc", "seeds"]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})
    return json_path, csv_path


def _print_cum_at_last(rows: list[dict]) -> None:
    last = N_TURNS - 1
    print(f"\n=== cumulative input tokens at turn {last} (per config) ===")
    by_cfg = {r["config"]: r for r in rows if r["turn"] == last}
    for cfg in [c["name"] for c in CONFIGS]:
        r = by_cfg.get(cfg)
        if r:
            print(f"  {cfg:<14} cum_tokens@{last}={r['cum_tokens_mean']:>10,.0f} "
                  f"sel_acc={r['selection_acc']:.2f}")


def _parse_list(s: str | None, cast, default):
    if not s:
        return default
    return [cast(x.strip()) for x in s.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Demo #7 v2 — multi-turn session driver")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--seeds", default=None, help="comma list, e.g. 0,1,2")
    p.add_argument("--configs", default=None, help="comma list of config names")
    p.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "runs" / "demo07" / "session_raw")
    p.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs" / "demo07")
    p.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy" / "spans")
    args = p.parse_args(argv)

    seeds = _parse_list(args.seeds, int, list(SEEDS))
    wanted = _parse_list(args.configs, str, None)
    configs = [c for c in CONFIGS if (wanted is None or c["name"] in wanted)]

    session_file = args.spans_dir / f"run-{PROXY_BENCH_RUN_ID}.jsonl"

    import yaml
    task_def = yaml.safe_load(TASK_PATH.read_text())
    timeout = int(task_def.get("timeout_seconds", 300))

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.spans_dir.mkdir(parents=True, exist_ok=True)
    session_raw_dir = args.raw_dir  # raw + session json share the dir

    total = len(configs) * len(seeds)
    print(f"[demo07-session] grid: {len(configs)} configs x {len(seeds)} seeds = {total} runs")
    print(f"[demo07-session] colmena session file: {session_file}")

    records: list[dict] = []
    i = 0
    for cfg in configs:
        for seed in seeds:
            i += 1
            rec = _run_cell(cfg, seed, args.model_alias, args.proxy_base_url,
                            timeout, args.raw_dir, session_raw_dir,
                            args.spans_dir, session_file)
            records.append(rec)
            last = rec["turns"][-1] if rec.get("turns") else None
            print(f"[{i}/{total}] {rec['config']:<14} seed={seed} "
                  f"turns={len(rec.get('turns', []))} "
                  f"cum@last={last['cum_tokens'] if last else 0:<8} "
                  f"{'HARD_ERR' if rec.get('hard_error') else 'ok'}"
                  + (f" :: {rec['error']}" if rec.get('error') else ""))

    rows = _aggregate(records)
    json_path, csv_path = _write_outputs(rows, args.runs_dir)
    (args.runs_dir / "session_records.json").write_text(
        json.dumps(records, indent=2, default=str))
    _print_cum_at_last(rows)
    print(f"\nwrote {json_path}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
