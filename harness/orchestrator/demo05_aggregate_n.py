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
                "total": [], "turn10": [], "usd": [], "output": [], "cached": [],
                "calls": [], "lat": [], "wall": [], "cold": [], "ram": [], "ttft": [],
                "quality": [], "cum": [], "per_turn": [], "pt_lat": [], "pt_calls": [],
                "loc": r.get("loc"), "version": r.get("framework_version", ""),
            })
            a["total"].append(r["total_input"])
            a["turn10"].append(r["turn10_input"])
            a["usd"].append(r["usd_total"])
            a["output"].append(r.get("total_output", 0))
            a["cached"].append(r.get("total_cached", 0))
            a["calls"].append(r.get("total_calls", 0))
            a["lat"].append(r.get("total_latency_ms", 0))
            a["wall"].append(r.get("wall_latency_ms") or 0)
            a["cold"].append(r.get("cold_start_ms") or 0)
            a["ram"].append(r.get("ram_peak_mb") or 0)
            a["ttft"].append(r.get("ttft_ms") or 0)
            a["quality"].append(1 if r.get("quality_ok") else 0)
            a["cum"].append(r["cumulative_input"])
            a["per_turn"].append(r["per_turn_input"])
            a["pt_lat"].append(r.get("per_turn_latency_ms") or [])
            a["pt_calls"].append(r.get("per_turn_calls") or [])
            a["loc"] = r.get("loc")

    out = {"n_passes": n_passes, "frameworks": []}
    for fw, a in acc.items():
        tm, ts = _mean_std(a["total"])
        t10m, t10s = _mean_std(a["turn10"])
        um, us = _mean_std(a["usd"])
        om, os_ = _mean_std(a["output"])
        cm, cs = _mean_std(a["cached"])
        callm, calls = _mean_std(a["calls"])
        latm, lats = _mean_std(a["lat"])
        wm, ws = _mean_std(a["wall"])
        coldm, colds = _mean_std(a["cold"])
        ramm, rams = _mean_std(a["ram"])
        ttftm, ttfts = _mean_std(a["ttft"])
        qrate = sum(a["quality"]) / len(a["quality"]) if a["quality"] else 0.0
        n_turns = max((len(c) for c in a["cum"]), default=0)
        cum_mean, cum_std, pt_mean, pt_lat_mean, pt_calls_mean = [], [], [], [], []
        for t in range(n_turns):
            m, s = _mean_std([c[t] for c in a["cum"] if t < len(c)])
            cum_mean.append(m); cum_std.append(s)
            pt_mean.append(_mean_std([c[t] for c in a["per_turn"] if t < len(c)])[0])
            pt_lat_mean.append(_mean_std([c[t] for c in a["pt_lat"] if t < len(c)])[0])
            pt_calls_mean.append(_mean_std([c[t] for c in a["pt_calls"] if t < len(c)])[0])
        out["frameworks"].append({
            "framework": fw, "framework_version": a["version"], "loc": a["loc"],
            "total_mean": tm, "total_std": ts,
            "turn10_mean": t10m, "turn10_std": t10s,
            "usd_mean": um, "usd_std": us,
            "output_mean": om, "output_std": os_,
            "cached_mean": cm, "cached_std": cs,
            "calls_mean": callm, "calls_std": calls,
            "latency_ms_mean": latm, "latency_ms_std": lats,
            "wall_latency_ms_mean": wm, "wall_latency_ms_std": ws,
            "cold_start_ms_mean": coldm, "cold_start_ms_std": colds,
            "ram_peak_mb_mean": ramm, "ram_peak_mb_std": rams,
            "ttft_ms_mean": ttftm, "ttft_ms_std": ttfts,
            "quality_pass_rate": qrate,
            "cum_mean": cum_mean, "cum_std": cum_std, "per_turn_mean": pt_mean,
            "per_turn_latency_ms_mean": pt_lat_mean, "per_turn_calls_mean": pt_calls_mean,
        })
    out["frameworks"].sort(key=lambda r: r["total_mean"])

    outpath = args.out or (REPO_ROOT / f"runs/demo05/report/agg_n{n_passes}.json")
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text(json.dumps(out, indent=2))

    # --- also write CSVs so the data is reusable without re-running the tests ---
    import csv
    summ = outpath.with_name(outpath.stem + "_summary.csv")
    with summ.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["framework", "version", "n_passes", "loc",
                    "total_in_mean", "total_in_std", "turn10_in_mean", "turn10_in_std",
                    "output_mean", "output_std", "cached_mean",
                    "usd_mean", "usd_std",
                    "calls_mean", "calls_std",
                    "provider_latency_ms_mean", "provider_latency_ms_std",
                    "wall_latency_ms_mean", "wall_latency_ms_std",
                    "ttft_ms_mean", "cold_start_ms_mean", "ram_peak_mb_mean",
                    "quality_pass_rate"])
        for r in out["frameworks"]:
            w.writerow([r["framework"], r["framework_version"], n_passes, r["loc"],
                        f"{r['total_mean']:.1f}", f"{r['total_std']:.1f}",
                        f"{r['turn10_mean']:.1f}", f"{r['turn10_std']:.1f}",
                        f"{r['output_mean']:.1f}", f"{r['output_std']:.1f}", f"{r['cached_mean']:.1f}",
                        f"{r['usd_mean']:.6f}", f"{r['usd_std']:.6f}",
                        f"{r['calls_mean']:.2f}", f"{r['calls_std']:.2f}",
                        f"{r['latency_ms_mean']:.1f}", f"{r['latency_ms_std']:.1f}",
                        f"{r['wall_latency_ms_mean']:.1f}", f"{r['wall_latency_ms_std']:.1f}",
                        f"{r['ttft_ms_mean']:.1f}", f"{r['cold_start_ms_mean']:.1f}",
                        f"{r['ram_peak_mb_mean']:.2f}", f"{r['quality_pass_rate']:.2f}"])
    perturn = outpath.with_name(outpath.stem + "_per_turn.csv")
    with perturn.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["framework", "turn", "cumulative_in_mean", "cumulative_in_std", "per_turn_in_mean"])
        for r in out["frameworks"]:
            for t, (cm, cs, pm) in enumerate(zip(r["cum_mean"], r["cum_std"], r["per_turn_mean"]), 1):
                w.writerow([r["framework"], t, f"{cm:.1f}", f"{cs:.1f}", f"{pm:.1f}"])
    print(f"aggregated {n_passes} passes → {outpath}")
    print(f"  csv: {summ.name}, {perturn.name}")
    for r in out["frameworks"]:
        print(f"  {r['framework']:11s} total {r['total_mean']:>9,.0f} ± {r['total_std']:>7,.0f}"
              f"  turn10 {r['turn10_mean']:>7,.0f} ± {r['turn10_std']:>6,.0f}"
              f"  usd ${r['usd_mean']:.5f}  loc {r['loc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
