"""Aggregate Task 4 (CSV analytical) runs into a naive-vs-expert summary + charts.

Reads the per-run outputs written by full_run.py under results/*-task04_csv_*/raw/
(each run JSON has variant, tokens (proxy-enriched), and success.judge_score for the
dataset_qa scorer). Groups by (strategy ∈ {naive, expert}, variant ∈ {S,M,L},
framework) → mean input tokens, mean accuracy, mean USD. Writes:
  runs/task04/task4_summary.json + task4_summary.csv
  runs/task04/plots/{tokens_asymptote,accuracy}.png

Usage: python harness/orchestrator/task4_aggregate.py
"""
from __future__ import annotations

import glob
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
PRICING = json.loads((HARNESS_DIR / "pricing_table.json").read_text())

VARIANT_ORDER = {"S": 0, "M": 1, "L": 2}


def _epoch(ts):
    from datetime import datetime
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()


def _colmena_window_tokens(run_file: str, ro: dict):
    """full_run.py attributes only ONE session-span per colmena run, which
    undercounts multi-call tasks (e.g. the SQL-tool expert ReAct loop). Recompute
    by summing the run's proxy session spans within its [started_at, ended_at]
    window. Returns (tokens_in, tokens_out) or (None, None) if spans unavailable.
    """
    p = Path(run_file)
    # results/<DATE>-task<NUM>/raw/colmena/<uuid>.json  →  session task<NUM>-<DATE>
    try:
        result_dir = p.parents[2].name                       # "<DATE>-task04_csv_expert"
        date, _, tasknum = result_dir.partition("-task")     # "<DATE>", "04_csv_expert"
        span_file = REPO_ROOT / "proxy" / "spans" / f"run-task{tasknum}-{date}.jsonl"
    except Exception:
        return None, None
    if not span_file.exists():
        return None, None
    t0, t1 = _epoch(ro.get("started_at")), _epoch(ro.get("ended_at"))
    if t0 is None or t1 is None:
        return None, None
    tin = tout = 0
    pad = 2.0  # small clock-skew pad
    for line in span_file.read_text().splitlines():
        if not line.strip():
            continue
        s = json.loads(line)
        ts = _epoch(s.get("ts_start"))
        if ts is None or not (t0 - pad <= ts <= t1 + pad):
            continue
        tin += int(s.get("tokens_input", 0))
        tout += int(s.get("tokens_output", 0))
    return (tin, tout) if tin else (None, None)
COLORS = {"colmena": "#1f9d55", "crewai": "#e15759", "langchain": "#4e79a7",
          "langgraph": "#f28e2b", "llamaindex": "#b07aa1", "google_adk": "#17a2b8"}


def _usd(tokens_in: float, tokens_out: float, model: str) -> float:
    m = PRICING["models"][model]
    return (tokens_in * m["input_per_1m"] + tokens_out * m["output_per_1m"]) / 1_000_000


def main() -> int:
    files = glob.glob(str(REPO_ROOT / "results/*-task04_csv_*/raw/*/*.json"))
    if not files:
        print("no Task 4 run files under results/*-task04_csv_*/raw/")
        return 1
    # (strategy, variant, framework) -> {tin:[], tout:[], acc:[], ok:int, n:int}
    g: dict[tuple, dict] = {}
    model = "gemini-2.5-flash"
    skipped = 0
    for f in files:
        ro = json.loads(Path(f).read_text())
        # Drop failed/empty runs (e.g. the early colmena-expert attempts that
        # errored with tin=0 before the run_task.sh .env fix) so they don't
        # pollute the means. A real run has no error and nonzero input tokens.
        if ro.get("error") or (ro.get("tokens") or {}).get("input", 0) == 0:
            skipped += 1
            continue
        tid = ro.get("task_id", "")
        if "naive" in tid:
            strat = "naive"
        elif "expert" in tid:
            strat = "expert"
        else:
            continue
        var = ro.get("variant", "?")
        fw = ro.get("framework", "?")
        model = ro.get("model_alias", model)
        k = (strat, var, fw)
        d = g.setdefault(k, {"tin": [], "tout": [], "acc": [], "ok": 0, "n": 0})
        d["n"] += 1
        succ = ro.get("success") or {}
        if succ.get("ok"):
            d["ok"] += 1
        if succ.get("judge_score") is not None:
            d["acc"].append(float(succ["judge_score"]))
        tin = int((ro.get("tokens") or {}).get("input", 0))
        tout = int((ro.get("tokens") or {}).get("output", 0))
        if fw == "colmena":  # full_run undercounts multi-call colmena → recompute from session spans
            wtin, wtout = _colmena_window_tokens(f, ro)
            if wtin is not None:
                tin, tout = wtin, wtout
        d["tin"].append(tin)
        d["tout"].append(tout)

    rows = []
    for (strat, var, fw), d in g.items():
        tin = statistics.mean(d["tin"]) if d["tin"] else 0
        tout = statistics.mean(d["tout"]) if d["tout"] else 0
        rows.append({
            "strategy": strat, "variant": var, "framework": fw, "n": d["n"],
            "tokens_in_mean": round(tin, 1),
            "tokens_in_std": round(statistics.stdev(d["tin"]), 1) if len(d["tin"]) > 1 else 0.0,
            "accuracy_mean": round(statistics.mean(d["acc"]), 4) if d["acc"] else None,
            "usd_mean": round(_usd(tin, tout, model), 6),
            "ok_rate": round(d["ok"] / d["n"], 3) if d["n"] else 0,
        })
    rows.sort(key=lambda r: (r["strategy"], VARIANT_ORDER.get(r["variant"], 9), r["framework"]))

    out = REPO_ROOT / "runs/task04"
    (out / "plots").mkdir(parents=True, exist_ok=True)
    (out / "task4_summary.json").write_text(json.dumps({"model": model, "rows": rows}, indent=2))
    import csv
    with (out / "task4_summary.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        cols = ["strategy", "variant", "framework", "n", "tokens_in_mean", "tokens_in_std",
                "accuracy_mean", "usd_mean", "ok_rate"]
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])

    _chart_tokens(rows, out / "plots" / "tokens_asymptote.png")
    _chart_accuracy(rows, out / "plots" / "accuracy.png")

    print(f"Task4 summary → {out}/task4_summary.csv ({len(rows)} groups, {skipped} failed/empty runs skipped)")
    for r in rows:
        acc = f"{r['accuracy_mean']*100:.0f}%" if r["accuracy_mean"] is not None else "—"
        print(f"  {r['strategy']:7s} {r['variant']} {r['framework']:11s} "
              f"tok_in {r['tokens_in_mean']:>9,.0f}  acc {acc:>4}  ok {r['ok_rate']*100:.0f}%  ${r['usd_mean']:.5f}")
    return 0


def _chart_tokens(rows, path):
    """Input tokens vs variant (S/M/L): naive grows, expert stays flat. Mean over frameworks."""
    fig, ax = plt.subplots(figsize=(8, 5))
    for strat, style in (("naive", "--o"), ("expert", "-s")):
        xs, ys = [], []
        for v in ("S", "M", "L"):
            vals = [r["tokens_in_mean"] for r in rows if r["strategy"] == strat and r["variant"] == v and r["tokens_in_mean"]]
            if vals:
                xs.append(v); ys.append(statistics.mean(vals))
        if xs:
            ax.plot(xs, ys, style, linewidth=2.2, markersize=8,
                    color="#c0392b" if strat == "naive" else "#1f9d55", label=strat)
            for x, y in zip(xs, ys):
                ax.text(x, y, f"{y:,.0f}", ha="center", va="bottom", fontsize=8)
    ax.set_yscale("log")
    ax.set_xlabel("Dataset size (S=500, M=5k, L=50k rows)")
    ax.set_ylabel("Mean input tokens (log scale)")
    ax.set_title("Task 4 — naive (CSV in prompt) vs expert (SQL tool): the strategy asymptote\n"
                 "averaged across frameworks (a strategy difference, not a framework one)")
    ax.legend(); ax.grid(alpha=0.3, which="both")
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def _chart_accuracy(rows, path):
    """Accuracy per framework, expert strategy (and naive if present), at the largest variant available."""
    fws = sorted({r["framework"] for r in rows})
    fig, ax = plt.subplots(figsize=(9, 5))
    width = 0.38
    import numpy as np
    x = np.arange(len(fws))
    for i, strat in enumerate(("naive", "expert")):
        vals = []
        for fw in fws:
            cand = [r for r in rows if r["framework"] == fw and r["strategy"] == strat
                    and r["accuracy_mean"] is not None]
            cand.sort(key=lambda r: VARIANT_ORDER.get(r["variant"], 9))
            vals.append(cand[-1]["accuracy_mean"] * 100 if cand else 0)
        ax.bar(x + (i - 0.5) * width, vals, width,
               label=strat, color="#c0392b" if strat == "naive" else "#1f9d55")
    ax.set_xticks(x); ax.set_xticklabels(fws, rotation=15)
    ax.set_ylim(0, 105); ax.set_ylabel("Accuracy (% of 20 questions)")
    ax.set_title("Task 4 — accuracy by framework (largest variant per strategy)")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
