"""Hero Demo #1 orchestrator — cumulative tokens/turn + USD + LOC across frameworks.

Each runner replays the fixed 10-turn script and emits per-turn boundary
timestamps (extras.turn_boundaries). We bucket proxy spans into turns by
timestamp, build the cumulative-input series, price it, count handler LOC, and
write report.md + chart_data.json.

Run with the proxy already up and BENCH_RUN_ID matching --session-id (so
Colmena's spans land in run-<session-id>.jsonl). Header-capable runners write
run-<run_id>.jsonl as usual.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR / "orchestrator"))
sys.path.insert(0, str(HARNESS_DIR))

from demo05_buckets import bucket_spans_by_turn  # noqa: E402
from demo05_loc import count_loc  # noqa: E402
from orchestrator.full_run import venv_python, _read_spans, _proxy_key, usd_per_run, PRICING  # noqa: E402

HEADER_CAPABLE = {"crewai", "langchain", "langgraph", "llamaindex", "google_adk"}

LOC_TARGETS = {
    "colmena": ["runners/colmena/runner/tasks/task05.py", "runners/colmena/dags/demo05_turn.json"],
    "crewai": ["runners/crewai/runner/tasks/task05.py"],
    "langchain": ["runners/langchain/runner/tasks/task05.py"],
    "langgraph": ["runners/langgraph/runner/tasks/task05.py"],
    "llamaindex": ["runners/llamaindex/runner/tasks/task05.py"],
    "google_adk": ["runners/google_adk/runner/tasks/task05.py"],
}


def _run_one(fw: str, task_path: Path, model_alias: str, proxy_base_url: str,
             out_dir: Path, run_id: str, timeout: int) -> dict | None:
    py = venv_python(fw)
    if not py.exists():
        print(f"  [skip] {fw}: no venv")
        return None
    fw_out = out_dir / fw
    fw_out.mkdir(parents=True, exist_ok=True)
    out_path = fw_out / f"{run_id}.json"
    env = os.environ.copy()
    env.update({
        "BENCH_RUN_ID": run_id,
        "LITELLM_PROXY_BASE_URL": proxy_base_url,
        "LITELLM_PROXY_API_KEY": _proxy_key(),
        "PYTHONPATH": f"{REPO_ROOT/'runners'/fw}:{REPO_ROOT/'runners'/'_bench_common'}",
    })
    proc = subprocess.run(
        [str(py), "-m", "runner", "--task", str(task_path), "--variant", "default",
         "--run-id", run_id, "--model-alias", model_alias,
         "--proxy-base-url", proxy_base_url, "--output", str(out_path),
         "--timeout-seconds", str(timeout)],
        env=env, capture_output=True, text=True, timeout=timeout + 30,
    )
    if proc.returncode != 0:
        out_path.with_suffix(".stderr").write_text(proc.stderr)
        print(f"  {fw}: exit {proc.returncode} (see .stderr)")
        return None
    return json.loads(out_path.read_text())


def _spans_for(fw: str, run_id: str, session_id: str, spans_dir: Path) -> list[dict]:
    name = run_id if fw in HEADER_CAPABLE else session_id
    return _read_spans(spans_dir / f"run-{name}.jsonl")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Hero demo #1 — context tax")
    p.add_argument("--task", type=Path, default=REPO_ROOT / "harness/tasks/05_context_scrubbing.yaml")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--session-id", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy" / "spans")
    p.add_argument("--frameworks", nargs="*", default=["colmena", "crewai"])
    args = p.parse_args(argv)

    import yaml
    task_def = yaml.safe_load(args.task.read_text())
    timeout = task_def.get("timeout_seconds", 300)

    results = []
    for fw in args.frameworks:
        print(f"==> {fw}")
        run_id = args.session_id if fw not in HEADER_CAPABLE else str(uuid.uuid4())
        ro = _run_one(fw, args.task, args.model_alias, args.proxy_base_url,
                      args.out_dir / "raw", run_id, timeout)
        if not ro:
            continue
        boundaries = (ro.get("extras") or {}).get("turn_boundaries") or []
        spans = _spans_for(fw, run_id, args.session_id, args.spans_dir)
        buckets = bucket_spans_by_turn(spans, boundaries)
        total_in = sum(buckets["per_turn_input"])
        total_out = sum(buckets["per_turn_output"])
        ro_tok = {"input": total_in, "output": total_out, "cached": 0}
        usd = usd_per_run({"tokens": ro_tok}, args.model_alias)
        loc = sum(count_loc(REPO_ROOT / f) for f in LOC_TARGETS.get(fw, []) if (REPO_ROOT / f).exists())
        results.append({
            "framework": fw,
            "framework_version": ro.get("framework_version", ""),
            "per_turn_input": buckets["per_turn_input"],
            "cumulative_input": buckets["cumulative_input"],
            "total_input": total_in,
            "total_output": total_out,
            "turn10_input": buckets["per_turn_input"][-1] if buckets["per_turn_input"] else 0,
            "usd_total": usd,
            "loc": loc,
            "answers": ro.get("answer"),
        })
        print(f"  {fw}: total_in={total_in} turn10_in={results[-1]['turn10_input']} loc={loc}")

    if not results:
        print("no results")
        return 1
    out = args.out_dir / "report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "chart_data.json").write_text(json.dumps(results, indent=2))
    (out / "report.md").write_text(render_report(results))
    print(f"\nreport → {out/'report.md'}")
    print((out / "report.md").read_text())
    return 0


def render_report(results: list[dict]) -> str:
    results = sorted(results, key=lambda r: r["total_input"])
    lines = [
        "# Hero Demo #1 — The Context Tax (multi-turn token asymptote)",
        "",
        "Fixed 10-turn report-assistant conversation. Tokens are provider-"
        "authoritative (captured at the proxy). Lower is better.",
        "",
        "| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |",
        "|---|---|--:|--:|--:|--:|",
    ]
    for r in results:
        lines.append(
            f"| {r['framework']} | {r['framework_version']} | {r['total_input']:,} "
            f"| {r['turn10_input']:,} | ${r['usd_total']:.6f} | {r['loc']} |"
        )
    lines += ["", "## Cumulative input tokens per turn", "",
              "| turn | " + " | ".join(r["framework"] for r in results) + " |",
              "|--:|" + "|".join("--:" for _ in results) + "|"]
    n_turns = max((len(r["cumulative_input"]) for r in results), default=0)
    for t in range(n_turns):
        row = [str(t + 1)]
        for r in results:
            cum = r["cumulative_input"]
            row.append(f"{cum[t]:,}" if t < len(cum) else "")
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "_Competitors run their **default idiomatic** multi-turn memory (full "
        "history, retained tool outputs). To match Colmena they would need to "
        "add manual history trimming, attachment caching, and base64 scrubbing — "
        "extra code Colmena provides built-in (extra LOC = 0)._",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
