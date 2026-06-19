"""Render Demo #7 v2 (multi-turn many-tools session) charts (PNG) — honest framing.

A realistic ~30-tool agent over a 10-turn conversation. THE hero metric is
CUMULATIVE input tokens per turn: colmena-lazy sends a catalog once and pulls
schemas on demand, so its cumulative line stays low/flat, while colmena-eager
(lazy OFF) and every competitor re-send all ~30 tool schemas each turn — their
cumulative climbs faster. Selection accuracy is reported straight (likely ~equal):
lazy is a SCALE/cost feature, not an accuracy claim.

Input:  runs/demo07/session_summary.json (list of per-(config, turn) dicts:
        {config, turn, cum_tokens_mean, per_turn_tokens_mean, selection_acc, ...})
Output: runs/demo07/plots/*.png

Charts:
  session_cum_tokens_vs_turn.png       — HERO: cumulative input tokens vs turn
  session_selection_vs_turn.png        — selection_acc (0–1.05) vs turn
  session_cum_tokens_at_turn10_bar.png — cum tokens at last turn per config (punchline)

Usage: python demo07_session_plots.py
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

COLORS = {
    LAZY: C_LAZY,
    EAGER: C_EAGER,
    "crewai": "#e15759",      # red
    "langchain": "#4e79a7",   # blue
    "langgraph": "#f28e2b",   # orange
    "llamaindex": "#b07aa1",  # purple
    "google_adk": "#17a2b8",  # teal
}
CONFIG_ORDER = [LAZY, EAGER, "crewai", "langchain", "langgraph",
                "llamaindex", "google_adk"]
_FALLBACK = ["#8c564b", "#bcbd22", "#7f7f7f", "#e377c2"]


def _color(name: str) -> str:
    return COLORS.get(name, _FALLBACK[hash(name) % len(_FALLBACK)])


def _style(name: str) -> dict:
    if name == LAZY:
        return {"linewidth": 2.8, "linestyle": "-", "marker": "o", "zorder": 5}
    if name == EAGER:
        return {"linewidth": 2.0, "linestyle": "--", "marker": "s", "zorder": 4}
    return {"linewidth": 1.5, "linestyle": "-", "marker": "o", "zorder": 2}


def _configs_present(rows: list[dict]) -> list[str]:
    seen = {r["config"] for r in rows}
    ordered = [c for c in CONFIG_ORDER if c in seen]
    return ordered + sorted(seen - set(ordered))


def _series(rows: list[dict], config: str, ykey: str) -> tuple[list, list]:
    """(x=turn, y=ykey) for one config, sorted by turn, y present only."""
    pts = [(r["turn"], r[ykey]) for r in rows
           if r["config"] == config and r.get(ykey) is not None
           and r.get("turn") is not None]
    pts.sort(key=lambda p: p[0])
    return [p[0] for p in pts], [p[1] for p in pts]


def cum_tokens_vs_turn(rows: list[dict], outdir: Path) -> "Path | None":
    """HERO: cumulative input tokens vs turn, one line per config."""
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for cfg in _configs_present(rows):
        xs, ys = _series(rows, cfg, "cum_tokens_mean")
        if not xs:
            continue
        ax.plot(xs, ys, color=_color(cfg), label=cfg, **_style(cfg))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_xlabel("Turn (0–9 of a 10-turn conversation)")
    ax.set_ylabel("Cumulative input tokens (mean over seeds, provider-authoritative)")
    ax.set_title(
        "Multi-turn ~30-tool agent: cumulative input tokens grow with the conversation\n"
        "colmena-lazy (green) sends a catalog once; eager + competitors re-send every schema each turn",
        fontsize=9.5)
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = outdir / "session_cum_tokens_vs_turn.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def selection_vs_turn(rows: list[dict], outdir: Path) -> "Path | None":
    """selection_acc (0–1.05) vs turn, one line per config (honest: ~equal)."""
    if not any(r.get("selection_acc") is not None for r in rows):
        return None
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
    ax.set_xlabel("Turn (0–9 of a 10-turn conversation)")
    ax.set_ylabel("Selection accuracy — right tool among confusers (0–1)")
    ax.set_title(
        "Selection accuracy holds across turns\n"
        "lazy keeps up with eager + competitors — the win is cost, not accuracy",
        fontsize=9.5)
    ax.legend(fontsize=7, loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = outdir / "session_selection_vs_turn.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def cum_tokens_at_last_bar(rows: list[dict], outdir: Path) -> "Path | None":
    """Punchline: cum tokens at the LAST turn per config; annotate lazy ratio."""
    if not rows:
        return None
    last = max(r["turn"] for r in rows)
    facet = [r for r in rows if r["turn"] == last]
    if not facet:
        return None
    names = _configs_present(facet)
    by_tok = {r["config"]: r.get("cum_tokens_mean") for r in facet}

    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = [_color(c) for c in names]
    vals = [by_tok.get(c) or 0 for c in names]
    bars = ax.bar(names, vals, color=colors)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f}",
                ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Cumulative input tokens at last turn (mean)")
    ax.set_title(f"Total input-token cost after a 10-turn conversation (at turn {last})",
                 fontsize=11)
    ax.tick_params(axis="x", labelrotation=20)
    ax.grid(axis="y", alpha=0.3)

    lazy_v = by_tok.get(LAZY)
    others = {c: v for c, v in by_tok.items() if c != LAZY and v}
    if lazy_v and others:
        worst_name = max(others, key=others.get)
        worst_v = others[worst_name]
        ratio = worst_v / lazy_v if lazy_v else 0
        ax.text(0.98, 0.95,
                f"colmena-lazy ≈ {lazy_v:,.0f} tok\n"
                f"highest ({worst_name}) ≈ {worst_v:,.0f} tok\n"
                f"→ {ratio:.1f}× fewer cumulative input tokens",
                transform=ax.transAxes, ha="right", va="top", fontsize=8,
                bbox=dict(boxstyle="round", fc="#eafaf0", ec=C_LAZY))
    fig.tight_layout()
    out = outdir / "session_cum_tokens_at_turn10_bar.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> int:
    summary_path = REPO_ROOT / "runs/demo07/session_summary.json"
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
    for fn in (cum_tokens_vs_turn, selection_vs_turn, cum_tokens_at_last_bar):
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
