"""Aggregate N independent demo05 passes into per-framework mean/std stats.

Reads runs/demo05/n<N>/run_*/report/chart_data.json (each a single full 6-fw
pass) and writes runs/demo05/report/agg_n<N>.json with, per framework:
  n, total_mean/std, turn10_mean/std, usd_mean/std, output_mean/std,
  cum_mean[]/cum_std[] (per-turn cumulative input), per_turn_mean[],
  loc (static), framework_version.

Usage: python demo05_aggregate_n.py [--base runs/demo05/n12] [--out runs/demo05/report/agg_n12.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent


def _mean_std(xs: list[float]) -> tuple[float, float]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return 0.0, 0.0
    m = statistics.mean(xs)
    s = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, s


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="aggregate N demo05 passes")
    p.add_argument("--base", type=Path, default=REPO_ROOT / "runs/demo05/n12")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    files = sorted(glob.glob(str(args.base / "run_*/report/chart_data.json")))
    if not files:
        print(f"no chart_data found under {args.base}")
        return 1

    # per framework -> accumulators
    acc: dict[str, dict] = {}
    n_passes = 0
    for f in files:
        data = json.loads(Path(f).read_text())
        # Only count a pass where every framework produced a nonzero total
        # (guards against a broken pass, e.g. missing env → colmena 0).
        if any(r.get("total_input", 0) <= 0 for r in data):
            print(f"  [skip pass] {f}: a framework had total_input<=0")
            continue
        n_passes += 1
        for r in data:
            fw = r["framework"]
            a = acc.setdefault(fw, {
                "total": [], "turn10": [], "usd": [], "output": [],
                "cum": [], "per_turn": [], "loc": r.get("loc"),
                "version": r.get("framework_version", ""),
            })
            a["total"].append(r["total_input"])
            a["turn10"].append(r["turn10_input"])
            a["usd"].append(r["usd_total"])
            a["output"].append(r.get("total_output", 0))
            a["cum"].append(r["cumulative_input"])
            a["per_turn"].append(r["per_turn_input"])
            a["loc"] = r.get("loc")

    out = {"n_passes": n_passes, "frameworks": []}
    for fw, a in acc.items():
        tm, ts = _mean_std(a["total"])
        t10m, t10s = _mean_std(a["turn10"])
        um, us = _mean_std(a["usd"])
        om, os = _mean_std(a["output"])
        n_turns = max((len(c) for c in a["cum"]), default=0)
        cum_mean, cum_std, pt_mean = [], [], []
        for t in range(n_turns):
            col = [c[t] for c in a["cum"] if t < len(c)]
            m, s = _mean_std(col)
            cum_mean.append(m); cum_std.append(s)
            ptcol = [c[t] for c in a["per_turn"] if t < len(c)]
            pm, _ = _mean_std(ptcol)
            pt_mean.append(pm)
        out["frameworks"].append({
            "framework": fw, "framework_version": a["version"], "loc": a["loc"],
            "total_mean": tm, "total_std": ts,
            "turn10_mean": t10m, "turn10_std": t10s,
            "usd_mean": um, "usd_std": us,
            "output_mean": om, "output_std": os,
            "cum_mean": cum_mean, "cum_std": cum_std, "per_turn_mean": pt_mean,
        })
    out["frameworks"].sort(key=lambda r: r["total_mean"])

    outpath = args.out or (REPO_ROOT / f"runs/demo05/report/agg_n{n_passes}.json")
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text(json.dumps(out, indent=2))
    print(f"aggregated {n_passes} passes → {outpath}")
    for r in out["frameworks"]:
        print(f"  {r['framework']:11s} total {r['total_mean']:>9,.0f} ± {r['total_std']:>7,.0f}"
              f"  turn10 {r['turn10_mean']:>7,.0f} ± {r['turn10_std']:>6,.0f}"
              f"  usd ${r['usd_mean']:.5f}  loc {r['loc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
