"""Render Demo #7 (many realistic confusable tools) charts (PNG) — honest framing.

The toolset is now realistic: N tools where the needle's whole confusable cluster
(e.g. refunds_billing: create_refund vs issue_store_credit vs cancel_order vs
get_refund_status vs escalate_to_billing) is always present. The model gets a
natural-language intent that never names a tool, so it must read the summaries to
pick the right one among genuinely similar siblings. Counts are 5 / 10 / 20.

Two honest dimensions, reported straight from the data:
  1) SELECTION ACCURACY — does picking the right tool among confusers degrade with
     more tools, and does colmena-lazy keep up with colmena-eager (the control:
     same engine, lazy OFF)? If lazy < eager, that's a real tradeoff and the chart
     shows it.
  2) TOKENS — colmena-lazy sends a catalog (name + summary) instead of every
     tool's full schema, so it should be the lowest-token config at scale.

Input:  runs/demo07/summary.json (list of per-(config, n_tools) dicts)
Output: runs/demo07/plots/*.png

Charts (no difficulty facets):
  accuracy_vs_tools.png   — HERO: selection_acc (0–1.05) vs n_tools, line/config
  tokens_vs_tools.png     — tokens_in_mean (LOG y) vs n_tools, line/config
  wrong_tool_vs_tools.png — wrong_tool_rate vs n_tools (the confusion signal)
  summary_at_20_bar.png   — grouped bars at n_tools=20: selection_acc + tokens

Reads whatever subset of the grid is present; skips a metric gracefully if absent.

Usage: python demo07_plots.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent

LAZY = "colmena-lazy"
EAGER = "colmena-eager"
C_LAZY = "#1f9d55"   # colmena green — the hero (lazy ON)
C_EAGER = "#7fbf7f"  # light green, dashed — the control (lazy OFF)

# Distinct per-competitor colors so each library is identifiable; the two colmena
# configs use the greens above (lazy bold solid, eager light dashed).
COLORS = {
    LAZY: C_LAZY,
    EAGER: C_EAGER,
    "crewai": "#e15759",      # red
    "langchain": "#4e79a7",   # blue
    "langgraph": "#f28e2b",   # orange
    "llamaindex": "#b07aa1",  # purple
    "google_adk": "#17a2b8",  # teal
}
# Stable draw order: colmena first (so its legend entries lead), then competitors.
CONFIG_ORDER = [LAZY, EAGER, "crewai", "langchain", "langgraph",
                "llamaindex", "google_adk"]
_FALLBACK = ["#8c564b", "#bcbd22", "#7f7f7f", "#e377c2"]


def _color(name: str) -> str:
    return COLORS.get(name, _FALLBACK[hash(name) % len(_FALLBACK)])


def _ntools(r: dict):
    """Tool count for a row. The summary schema uses ``n_tools``; older raw rows
    used ``count``. Accept either."""
    return r.get("n_tools", r.get("count"))


def _style(name: str) -> dict:
    """Per-config line style: lazy bold solid, eager dashed, competitors thin."""
    if name == LAZY:
        return {"linewidth": 2.8, "linestyle": "-", "marker": "o", "zorder": 5}
    if name == EAGER:
        return {"linewidth": 2.0, "linestyle": "--", "marker": "s", "zorder": 4}
    return {"linewidth": 1.5, "linestyle": "-", "marker": "o", "zorder": 2}


def _configs_present(rows: list[dict]) -> list[str]:
    seen = {r["config"] for r in rows}
    ordered = [c for c in CONFIG_ORDER if c in seen]
    # include any unexpected configs deterministically at the end
    return ordered + sorted(seen - set(ordered))


def _series(rows: list[dict], config: str, ykey: str) -> tuple[list, list]:
    """(x=n_tools, y=ykey) for one config, sorted by n_tools, y present only."""
    pts = [(_ntools(r), r[ykey]) for r in rows
           if r["config"] == config and r.get(ykey) is not None
           and _ntools(r) is not None]
    pts.sort(key=lambda p: p[0])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return xs, ys


def accuracy_vs_tools(rows: list[dict], outdir: Path) -> "Path | None":
    """HERO: selection_acc (0–1.05) vs #tools, one line per config.

    Does picking the right tool among confusers degrade as the tool count grows,
    and does colmena-lazy keep up with colmena-eager?
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for cfg in _configs_present(rows):
        xs, ys = _series(rows, cfg, "selection_acc")
        if not xs:
            continue
        ax.plot(xs, ys, color=_color(cfg), label=cfg, **_style(cfg))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Number of tools (needle's confusable cluster + distractors)")
    ax.set_ylabel("Selection accuracy — right tool among confusers (0–1)")
    ax.set_title(
        "Picking the right tool among confusable siblings\n"
        "does accuracy hold as #tools grows? does colmena-lazy keep up with "
        "colmena-eager?",
        fontsize=9.5)
    ax.legend(fontsize=7, loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = outdir / "accuracy_vs_tools.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def tokens_vs_tools(rows: list[dict], outdir: Path) -> "Path | None":
    """Input tokens (LOG y) vs #tools, one line per config."""
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for cfg in _configs_present(rows):
        xs, ys = _series(rows, cfg, "tokens_in_mean")
        if not xs:
            continue
        ax.plot(xs, ys, color=_color(cfg), label=cfg, **_style(cfg))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_yscale("log")
    ax.set_xlabel("Number of tools (needle's confusable cluster + distractors)")
    ax.set_ylabel("Input tokens (mean, provider-authoritative) — log scale")
    ax.set_title(
        "Lazy tool loading: fewer input tokens at scale\n"
        "colmena-lazy (green) sends a catalog, not every schema",
        fontsize=9.5)
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    out = outdir / "tokens_vs_tools.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def wrong_tool_vs_tools(rows: list[dict], outdir: Path) -> "Path | None":
    """wrong_tool_rate vs #tools, one line per config (the confusion signal)."""
    if not any(r.get("wrong_tool_rate") is not None for r in rows):
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for cfg in _configs_present(rows):
        xs, ys = _series(rows, cfg, "wrong_tool_rate")
        if not xs:
            continue
        ax.plot(xs, ys, color=_color(cfg), label=cfg, **_style(cfg))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Number of tools (needle's confusable cluster + distractors)")
    ax.set_ylabel("Wrong-tool rate — called a cluster sibling, not the needle")
    ax.set_title(
        "Confusion signal: how often a sibling tool is called instead of the needle\n"
        "lower is better; rises if more tools make the cluster harder to navigate",
        fontsize=9.5)
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = outdir / "wrong_tool_vs_tools.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def summary_at_20_bar(rows: list[dict], outdir: Path) -> "Path | None":
    """Punchline: at n_tools=20, grouped view of selection_acc + tokens per config.

    Two stacked panels sharing the x axis: top = selection accuracy bars,
    bottom = input tokens bars (log). colmena-lazy green; token ratio vs the
    cheapest competitor annotated.
    """
    facet = [r for r in rows if _ntools(r) == 20]
    if not facet:
        return None
    names = _configs_present(facet)
    by_acc = {r["config"]: r.get("selection_acc") for r in facet}
    by_tok = {r["config"]: r.get("tokens_in_mean") for r in facet}

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    colors = [_color(c) for c in names]

    acc_vals = [by_acc.get(c) or 0 for c in names]
    bars1 = ax1.bar(names, acc_vals, color=colors)
    for b, v in zip(bars1, acc_vals):
        ax1.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}",
                 ha="center", va="bottom", fontsize=8)
    ax1.set_ylim(0, 1.1)
    ax1.set_ylabel("Selection accuracy")
    ax1.set_title("At 20 tools: selection accuracy (top) and input tokens (bottom)",
                  fontsize=11)
    ax1.grid(axis="y", alpha=0.3)

    tok_vals = [by_tok.get(c) or 0 for c in names]
    bars2 = ax2.bar(names, tok_vals, color=colors)
    for b, v in zip(bars2, tok_vals):
        ax2.text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f}",
                 ha="center", va="bottom", fontsize=8)
    ax2.set_yscale("log")
    ax2.set_ylabel("Input tokens (mean, log)")
    ax2.tick_params(axis="x", labelrotation=20)
    ax2.grid(axis="y", alpha=0.3, which="both")

    lazy_v = by_tok.get(LAZY)
    competitors = {c: v for c, v in by_tok.items()
                   if c not in (LAZY, EAGER) and v}
    if lazy_v and competitors:
        best_comp_name = min(competitors, key=competitors.get)
        best_comp_v = competitors[best_comp_name]
        ratio = best_comp_v / lazy_v if lazy_v else 0
        ax2.text(0.98, 0.95,
                 f"colmena-lazy ≈ {lazy_v:,.0f} tok\n"
                 f"cheapest competitor ({best_comp_name}) ≈ {best_comp_v:,.0f} tok\n"
                 f"→ {ratio:.1f}× fewer input tokens",
                 transform=ax2.transAxes, ha="right", va="top", fontsize=8,
                 bbox=dict(boxstyle="round", fc="#eafaf0", ec=C_LAZY))
    fig.tight_layout()
    out = outdir / "summary_at_20_bar.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> int:
    summary_path = REPO_ROOT / "runs/demo07/summary.json"
    if not summary_path.exists():
        print(f"no summary at {summary_path}")
        return 1
    rows = json.loads(summary_path.read_text())
    if not rows:
        print(f"summary is empty: {summary_path}")
        return 1
    outdir = REPO_ROOT / "runs/demo07/plots"
    outdir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for fn in (accuracy_vs_tools, tokens_vs_tools, wrong_tool_vs_tools,
               summary_at_20_bar):
        try:
            out = fn(rows, outdir)
            if out:
                written.append(out)
                print(f"  ok: {fn.__name__} -> {out}")
            else:
                print(f"  skip: {fn.__name__} — no rows/metric")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")

    print(f"plots -> {outdir}  ({len(written)} written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
