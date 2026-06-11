"""Full Task run across all 6 frameworks → aggregated stats + comparative report.

Drives each framework's runner in its own pinned venv, N repetitions, then
enriches every run with provider-authoritative token counts from the proxy
spans (METHODOLOGY §4), aggregates, computes USD cost from the pricing
table, and writes a markdown report.

Span correlation:
  - Header-capable runners (crewai, langchain, langgraph, llamaindex,
    google_adk) tag each call with `x-bench-run-id`, so the proxy writes
    proxy/spans/run-<run_id>.jsonl per rep.
  - Colmena can't forward the header, so its spans land in the proxy's
    session file run-<session_id>.jsonl. We consume those in call order
    (reps run sequentially, one LLM call each).

Assumes the proxy is already running with BENCH_RUN_ID=<session_id>
(scripts/run_task.sh handles that). Reads the framework→venv map by
convention: runners/<framework>/.venv/bin/python.
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
sys.path.insert(0, str(HARNESS_DIR))

from orchestrator.aggregate import _stat  # noqa: E402
from orchestrator import report as report_mod  # noqa: E402

FRAMEWORKS = ["colmena", "crewai", "langchain", "langgraph", "llamaindex", "google_adk"]
HEADER_CAPABLE = {"crewai", "langchain", "langgraph", "llamaindex", "google_adk"}

PRICING = json.loads((HARNESS_DIR / "pricing_table.json").read_text())


def venv_python(framework: str) -> Path:
    return REPO_ROOT / "runners" / framework / ".venv" / "bin" / "python"


def _read_spans(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_framework(
    framework: str,
    task_path: Path,
    variant: str,
    model_alias: str,
    proxy_base_url: str,
    n: int,
    out_dir: Path,
    session_id: str,
    spans_dir: Path,
) -> list[dict]:
    """Run N reps, return enriched run-output dicts (tokens from proxy spans)."""
    py = venv_python(framework)
    if not py.exists():
        print(f"  [skip] {framework}: no venv at {py} (run setup_all.sh)")
        return []

    fw_out = out_dir / framework
    fw_out.mkdir(parents=True, exist_ok=True)
    common_dir = REPO_ROOT / "runners" / "_bench_common"
    runner_dir = REPO_ROOT / "runners" / framework

    run_ids: list[str] = []
    for rep in range(n):
        run_id = str(uuid.uuid4())
        run_ids.append(run_id)
        out_path = fw_out / f"{run_id}.json"
        env = os.environ.copy()
        env.update({
            "BENCH_RUN_ID": run_id,
            "LITELLM_PROXY_BASE_URL": proxy_base_url,
            "LITELLM_PROXY_API_KEY": _proxy_key(),
            "PYTHONPATH": f"{runner_dir}:{common_dir}",
        })
        proc = subprocess.run(
            [str(py), "-m", "runner",
             "--task", str(task_path), "--variant", variant,
             "--run-id", run_id, "--model-alias", model_alias,
             "--proxy-base-url", proxy_base_url, "--output", str(out_path),
             "--timeout-seconds", "60"],
            env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            (out_path.with_suffix(".stderr")).write_text(proc.stderr)
        print(f"  {framework} rep {rep + 1}/{n}: exit {proc.returncode}")

    # Colmena session spans, consumed in order.
    session_spans = _read_spans(spans_dir / f"run-{session_id}.jsonl") if framework not in HEADER_CAPABLE else []
    session_iter = iter(session_spans)

    enriched: list[dict] = []
    for run_id in run_ids:
        out_path = fw_out / f"{run_id}.json"
        if not out_path.exists():
            continue
        ro = json.loads(out_path.read_text())
        if framework in HEADER_CAPABLE:
            spans = _read_spans(spans_dir / f"run-{run_id}.jsonl")
        else:
            nxt = next(session_iter, None)
            spans = [nxt] if nxt else []
        # Proxy is authoritative for tokens.
        if spans:
            ro["tokens"]["input"] = sum(s.get("tokens_input", 0) for s in spans)
            ro["tokens"]["output"] = sum(s.get("tokens_output", 0) for s in spans)
            ro["tokens"]["cached"] = sum(s.get("tokens_cached", 0) for s in spans)
            ttfts = [s["ttft_ms"] for s in spans if s.get("ttft_ms")]
            if ttfts:
                ro["ttft_ms"] = ttfts[0]
        ro["_span_count"] = len(spans)
        enriched.append(ro)
        out_path.write_text(json.dumps(ro, indent=2))
    return enriched


def _proxy_key() -> str:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("LITELLM_MASTER_KEY="):
                return line.split("=", 1)[1].strip()
    return "sk-bench-runner-do-not-use-in-prod"


def usd_per_run(ro: dict, model_alias: str) -> float:
    m = PRICING["models"][model_alias]
    ti = ro["tokens"]["input"]
    tc = ro["tokens"].get("cached", 0)
    to = ro["tokens"]["output"]
    uncached_in = max(0, ti - tc)
    cost = (
        uncached_in * m["input_per_1m"]
        + tc * m.get("cached_input_per_1m", m["input_per_1m"])
        + to * m["output_per_1m"]
    ) / 1_000_000
    return cost


def aggregate_framework(framework: str, runs: list[dict], model_alias: str) -> dict | None:
    if not runs:
        return None
    n_failed = sum(1 for r in runs if not r["success"]["ok"])
    agg = {
        "task_id": runs[0]["task_id"],
        "variant": runs[0]["variant"],
        "framework": framework,
        "framework_version": runs[0].get("framework_version", ""),
        "model_alias": model_alias,
        "n": len(runs),
        "n_failed": n_failed,
        "success_rate": (len(runs) - n_failed) / len(runs),
        "stats": {
            "latency_ms": _stat([r["latency_ms"] for r in runs]),
            "cold_start_ms": _stat([r.get("cold_start_ms", 0) for r in runs]),
            "tokens_input": _stat([r["tokens"]["input"] for r in runs]),
            "tokens_output": _stat([r["tokens"]["output"] for r in runs]),
            "tokens_cached": _stat([r["tokens"].get("cached", 0) for r in runs]),
            "ram_peak_mb": _stat([r.get("ram_peak_mb", 0) for r in runs]),
        },
        "cost": {
            "usd_per_run": _stat([usd_per_run(r, model_alias) for r in runs]),
            "pricing_table_date": PRICING["snapshot_date"],
        },
    }
    return agg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="full task run across all frameworks")
    p.add_argument("--task", type=Path, required=True)
    p.add_argument("--variant", default="default")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--session-id", required=True, help="proxy BENCH_RUN_ID for colmena spans")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy" / "spans")
    p.add_argument("--frameworks", nargs="*", default=FRAMEWORKS)
    args = p.parse_args(argv)

    aggregates = []
    for fw in args.frameworks:
        print(f"==> {fw}")
        runs = run_framework(
            fw, args.task, args.variant, args.model_alias, args.proxy_base_url,
            args.n, args.out_dir / "raw", args.session_id, args.spans_dir,
        )
        agg = aggregate_framework(fw, runs, args.model_alias)
        if agg:
            agg_dir = args.out_dir / "aggregated" / agg["task_id"]
            agg_dir.mkdir(parents=True, exist_ok=True)
            (agg_dir / f"{fw}.json").write_text(json.dumps(agg, indent=2))
            aggregates.append(agg)

    if not aggregates:
        print("no aggregates produced")
        return 1

    report_dir = args.out_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    md = render_report(aggregates)
    (report_dir / "report.md").write_text(md)
    print("\n" + md)
    print(f"report → {report_dir / 'report.md'}")
    return 0


def render_report(aggregates: list[dict]) -> str:
    first = aggregates[0]
    # Order by mean total tokens (cheapest overhead first).
    aggregates = sorted(aggregates, key=lambda a: a["stats"]["tokens_input"]["mean"] + a["stats"]["tokens_output"]["mean"])
    lines = [
        f"# Task `{first['task_id']}` — comparative report",
        "",
        f"Model: `{first['model_alias']}` · N={first['n']} per framework · "
        f"pricing snapshot {first['cost']['pricing_table_date']}",
        "",
        "| Framework | ver | success | p50 lat (ms) | p95 lat (ms) | tok in | tok out | USD/run | USD/1k runs |",
        "|---|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for a in aggregates:
        s = a["stats"]
        usd = a["cost"]["usd_per_run"]["mean"]
        lines.append(
            f"| {a['framework']} | {a['framework_version']} "
            f"| {a['success_rate']*100:.0f}% "
            f"| {s['latency_ms']['p50']:.0f} | {s['latency_ms']['p95']:.0f} "
            f"| {s['tokens_input']['mean']:.0f} | {s['tokens_output']['mean']:.0f} "
            f"| ${usd:.6f} | ${usd*1000:.3f} |"
        )
    lines += [
        "",
        "_Tokens are provider-authoritative (captured at the proxy). Latency is "
        "wall-clock measured by each runner. Cost uses the dated pricing table; "
        "cached-input discount applied where the provider reports cached tokens._",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
