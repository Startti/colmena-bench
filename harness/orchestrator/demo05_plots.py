"""Render all demo05 charts (PNG) from the aggregated N-pass stats.

Input: runs/demo05/report/agg_n<N>.json (from demo05_aggregate_n.py).
Output: runs/demo05/report/plots/*.png

Charts:
  1 bar_total_tokens   — total input tokens, mean ± std, per framework
  2 line_cumulative    — cumulative input tokens per turn (mean ± std band)
  3 line_per_turn      — per-turn input tokens (measured) — each turn's cost
  4 bar_usd            — USD per 10-turn conversation (mean ± std) + at-scale note
  5 multiplier_curve   — competitor-median / colmena ratio per turn (compounding)
  6 quadrant           — cost (tokens) x maintained code (LOC) positioning
  7 loc_bar            — handler Code LOC per fw + Colmena declarative DAG annotated
  8 stacked_composition— ILLUSTRATIVE (estimated) per-turn input breakdown

Usage: python demo05_plots.py [--agg runs/demo05/report/agg_n12.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent

COLMENA = "colmena"
C_HI = "#1f9d55"   # colmena green (the hero — always bold/highlighted)
C_ACCENT = "#c0392b"

# Distinct per-competitor colors so each library is identifiable; Colmena stays
# the bold green hero (also drawn thicker/bigger via the `hi` flag in each chart).
COLORS = {
    "colmena": C_HI,
    "crewai": "#e15759",      # red
    "langchain": "#4e79a7",   # blue
    "langgraph": "#f28e2b",   # orange
    "llamaindex": "#b07aa1",  # purple
    "google_adk": "#17a2b8",  # teal
}
_FALLBACK = ["#8c564b", "#bcbd22", "#7f7f7f", "#e377c2"]

# Scenario constants for the ILLUSTRATIVE composition chart (estimated, not measured)
DOC_TOK = 3000          # report tokens, re-sent each turn by competitors
CHART_TOK = 8000        # one base64 chart ≈ 8k tokens, retained thereafter
CHART_TURNS = {2, 5, 8}  # 0-based turns that generate a chart


def _fw(agg, name):
    return next((r for r in agg["frameworks"] if r["framework"] == name), None)


def _color(name):
    if name in COLORS:
        return COLORS[name]
    return _FALLBACK[hash(name) % len(_FALLBACK)]


def bar_total_tokens(agg, outdir):
    fws = agg["frameworks"]
    names = [r["framework"] for r in fws]
    means = [r["total_mean"] for r in fws]
    stds = [r["total_std"] for r in fws]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(names, means, yerr=stds, capsize=5,
                  color=[_color(n) for n in names])
    ax.set_ylabel("Total input tokens over 10 turns")
    ax.set_title(f"Context tax — total input tokens (mean ± std, N={agg['n_passes']})")
    for b, m in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, m, f"{m:,.0f}",
                ha="center", va="bottom", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "1_bar_total_tokens.png", dpi=150); plt.close(fig)


def line_cumulative(agg, outdir):
    fig, ax = plt.subplots(figsize=(8, 5))
    for r in agg["frameworks"]:
        cm = r["cum_mean"]; cs = r["cum_std"]
        x = list(range(1, len(cm) + 1))
        hi = r["framework"] == COLMENA
        ax.plot(x, cm, marker="o", linewidth=2.5 if hi else 1.5,
                color=_color(r["framework"]),
                label=r["framework"], zorder=3 if hi else 2)
        ax.fill_between(x, [m - s for m, s in zip(cm, cs)],
                        [m + s for m, s in zip(cm, cs)],
                        color=_color(r["framework"]), alpha=0.15)
    ax.set_xlabel("Conversation turn"); ax.set_ylabel("Cumulative input tokens")
    ax.set_title(f"The context tax compounds (mean ± std, N={agg['n_passes']})")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "2_line_cumulative.png", dpi=150); plt.close(fig)


def line_per_turn(agg, outdir):
    fig, ax = plt.subplots(figsize=(8, 5))
    for r in agg["frameworks"]:
        pt = r["per_turn_mean"]; x = list(range(1, len(pt) + 1))
        hi = r["framework"] == COLMENA
        ax.plot(x, pt, marker="o", linewidth=2.5 if hi else 1.5,
                color=_color(r["framework"]), label=r["framework"], zorder=3 if hi else 2)
    ax.set_xlabel("Conversation turn"); ax.set_ylabel("Input tokens that turn")
    ax.set_title(f"Per-turn input cost (measured, N={agg['n_passes']})")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "3_line_per_turn.png", dpi=150); plt.close(fig)


def bar_usd(agg, outdir):
    fws = agg["frameworks"]
    names = [r["framework"] for r in fws]
    means = [r["usd_mean"] for r in fws]
    stds = [r["usd_std"] for r in fws]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(names, means, yerr=stds, capsize=5, color=[_color(n) for n in names])
    ax.set_ylabel("USD per 10-turn conversation")
    ax.set_title(f"Cost per conversation (mean ± std, N={agg['n_passes']}) — gemini-2.5-flash")
    for b, m in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, m, f"${m:.4f}", ha="center", va="bottom", fontsize=8)
    # at-scale projection: 1,000 conversations/day → $/year
    col = _fw(agg, COLMENA)
    comp = [r for r in fws if r["framework"] != COLMENA]
    med = sorted(r["usd_mean"] for r in comp)[len(comp) // 2]
    col_yr = col["usd_mean"] * 1000 * 365
    med_yr = med * 1000 * 365
    ax.text(0.98, 0.95,
            f"At 1,000 conversations/day:\n  colmena ≈ ${col_yr:,.0f}/yr\n"
            f"  competitor median ≈ ${med_yr:,.0f}/yr\n  → save ≈ ${med_yr-col_yr:,.0f}/yr",
            transform=ax.transAxes, ha="right", va="top", fontsize=8,
            bbox=dict(boxstyle="round", fc="#fff5e6", ec="#d9a441"))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "4_bar_usd.png", dpi=150); plt.close(fig)


def multiplier_curve(agg, outdir):
    col = _fw(agg, COLMENA)
    comp = [r for r in agg["frameworks"] if r["framework"] != COLMENA]
    n = len(col["cum_mean"])
    # competitor median cumulative per turn
    med = []
    for t in range(n):
        vals = sorted(r["cum_mean"][t] for r in comp if t < len(r["cum_mean"]))
        med.append(vals[len(vals) // 2])
    ratio = [med[t] / col["cum_mean"][t] if col["cum_mean"][t] else 0 for t in range(n)]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(range(1, n + 1), ratio, marker="o", color=C_ACCENT, linewidth=2.5)
    for t, r in enumerate(ratio):
        ax.text(t + 1, r, f"{r:.0f}×", ha="center", va="bottom", fontsize=8)
    ax.set_xlabel("Conversation turn"); ax.set_ylabel("Competitor median ÷ Colmena")
    ax.set_title("Colmena's advantage compounds with conversation length")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "5_multiplier_curve.png", dpi=150); plt.close(fig)


def quadrant(agg, outdir):
    fig, ax = plt.subplots(figsize=(7, 6))
    for r in agg["frameworks"]:
        hi = r["framework"] == COLMENA
        ax.scatter(r["total_mean"], r["loc"], s=180 if hi else 110,
                   color=_color(r["framework"]), edgecolor="black", zorder=3 if hi else 2)
        ax.annotate(r["framework"], (r["total_mean"], r["loc"]),
                    textcoords="offset points", xytext=(8, 6), fontsize=9)
    ax.set_xlabel("Total input tokens over 10 turns  (← cheaper)")
    ax.set_ylabel("Maintained handler code (LOC)  (← less)")
    ax.set_title("Positioning: cost × maintained code (bottom-left wins)")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "6_quadrant.png", dpi=150); plt.close(fig)


def loc_bar(agg, outdir):
    fws = sorted(agg["frameworks"], key=lambda r: r["loc"])
    names = [r["framework"] for r in fws]
    locs = [r["loc"] for r in fws]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(names, locs, color=[_color(n) for n in names])
    for b, m in zip(bars, locs):
        ax.text(b.get_x() + b.get_width() / 2, m, str(m), ha="center", va="bottom", fontsize=8)
    # annotate colmena's declarative DAG (config, not code)
    ci = names.index(COLMENA)
    ax.text(ci, locs[ci] + 4, "+ 71-line\ndeclarative DAG\n(config, not code)",
            ha="center", va="bottom", fontsize=7, color=C_HI)
    ax.set_ylabel("Imperative handler code (LOC)")
    ax.set_title("Node vs code — maintained imperative code (Demo 05)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "7_loc_bar.png", dpi=150); plt.close(fig)


def stacked_composition(agg, outdir):
    """ILLUSTRATIVE (estimated) per-turn input composition: a competitor vs colmena.

    Uses scenario constants (doc≈3000 tok re-sent each turn; each chart≈8000 tok
    retained). NOT a proxy measurement — an explanatory model of WHY competitors
    grow. Colmena bars use the measured per-turn means.
    """
    n = len(agg["frameworks"][0]["per_turn_mean"])
    turns = list(range(1, n + 1))
    # competitor (modeled): doc every turn after attach + accumulated charts + history
    charts_so_far = 0
    comp_doc, comp_charts, comp_hist = [], [], []
    comp = max(agg["frameworks"], key=lambda r: r["total_mean"])
    for t in range(n):
        if t in CHART_TURNS:
            charts_so_far += 1
        doc = DOC_TOK if t >= 0 else 0
        charts = CHART_TOK * charts_so_far
        total = comp["per_turn_mean"][t]
        hist = max(0, total - doc - charts)
        comp_doc.append(doc); comp_charts.append(charts); comp_hist.append(hist)
    col = _fw(agg, COLMENA)["per_turn_mean"]

    fig, ax = plt.subplots(figsize=(9, 5))
    w = 0.38
    xs = [t - w / 2 for t in turns]
    ax.bar(xs, comp_doc, w, label="report doc (re-sent)", color="#d9a441")
    ax.bar(xs, comp_charts, w, bottom=comp_doc, label="base64 charts (retained)", color="#c0392b")
    ax.bar(xs, comp_hist, w, bottom=[d + c for d, c in zip(comp_doc, comp_charts)],
           label="conversation history", color="#9aa0a6")
    ax.bar([t + w / 2 for t in turns], col, w, label="colmena (measured, all-in)", color=C_HI)
    ax.set_xticks(turns)
    ax.set_xlabel("Conversation turn"); ax.set_ylabel("Input tokens that turn")
    ax.set_title(f"Where the tokens go — {comp['framework']} (estimated) vs colmena (measured)")
    ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "8_stacked_composition.png", dpi=150); plt.close(fig)


def bar_latency(agg, outdir):
    fws = agg["frameworks"]
    names = [r["framework"] for r in fws]
    # total provider latency over the conversation (sum of all LLM calls), seconds
    means = [r.get("latency_ms_mean", 0) / 1000 for r in fws]
    stds = [r.get("latency_ms_std", 0) / 1000 for r in fws]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(names, means, yerr=stds, capsize=5, color=[_color(n) for n in names])
    for b, m in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, m, f"{m:.1f}s", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Total provider latency over 10 turns (s)")
    ax.set_title(f"Provider latency (sum of LLM calls, mean ± std, N={agg['n_passes']})\n"
                 "note: dominated by the model; reflects context size + #calls")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "9_bar_latency.png", dpi=150); plt.close(fig)


def line_calls(agg, outdir):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for r in agg["frameworks"]:
        cc = r.get("per_turn_calls_mean") or []
        if not cc:
            continue
        x = list(range(1, len(cc) + 1))
        hi = r["framework"] == COLMENA
        ax.plot(x, cc, marker="o", linewidth=2.5 if hi else 1.5,
                color=_color(r["framework"]), label=r["framework"], zorder=3 if hi else 2)
    ax.set_xlabel("Conversation turn"); ax.set_ylabel("LLM calls that turn")
    ax.set_title(f"LLM calls per turn (mean, N={agg['n_passes']})")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "10_line_calls.png", dpi=150); plt.close(fig)


def bar_ram(agg, outdir):
    fws = agg["frameworks"]
    names = [r["framework"] for r in fws]
    means = [r.get("ram_peak_mb_mean", 0) for r in fws]
    stds = [r.get("ram_peak_mb_std", 0) for r in fws]
    order = sorted(range(len(names)), key=lambda i: means[i])
    names = [names[i] for i in order]; means = [means[i] for i in order]; stds = [stds[i] for i in order]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(names, means, yerr=stds, capsize=5, color=[_color(n) for n in names])
    for b, m in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, m, f"{m:,.0f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Peak RSS (MB)")
    ax.set_title(f"Peak memory of the runner process (mean ± std, N={agg['n_passes']})\n"
                 "in-process work only (shared proxy excluded); Colmena incl. its Rust engine")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "11_bar_ram.png", dpi=150); plt.close(fig)


def bar_cpu(agg, outdir):
    fws = agg["frameworks"]
    names = [r["framework"] for r in fws]
    means = [r.get("cpu_total_s_mean", 0) for r in fws]
    stds = [r.get("cpu_total_s_std", 0) for r in fws]
    order = sorted(range(len(names)), key=lambda i: means[i])
    names = [names[i] for i in order]; means = [means[i] for i in order]; stds = [stds[i] for i in order]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.bar(names, means, yerr=stds, capsize=5, color=[_color(n) for n in names])
    for b, m in zip(bars, means):
        ax.text(b.get_x() + b.get_width() / 2, m, f"{m:.1f}s", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("CPU time over 10 turns (user+sys, s)")
    ax.set_title(f"CPU work of the runner process (mean ± std, N={agg['n_passes']})\n"
                 "actual compute, excludes time waiting on the model")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(outdir / "12_bar_cpu.png", dpi=150); plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="render demo05 charts")
    p.add_argument("--agg", type=Path, default=None)
    args = p.parse_args(argv)
    agg_path = args.agg
    if agg_path is None:
        cands = sorted((REPO_ROOT / "runs/demo05/report").glob("agg_n*.json"))
        if not cands:
            print("no agg_n*.json found — run demo05_aggregate_n.py first")
            return 1
        agg_path = cands[-1]
    agg = json.loads(Path(agg_path).read_text())
    outdir = REPO_ROOT / "runs/demo05/report/plots"
    outdir.mkdir(parents=True, exist_ok=True)
    for fn in (bar_total_tokens, line_cumulative, line_per_turn, bar_usd,
               multiplier_curve, quadrant, loc_bar, stacked_composition,
               bar_latency, line_calls, bar_ram, bar_cpu):
        try:
            fn(agg, outdir)
            print(f"  ok: {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"plots → {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
