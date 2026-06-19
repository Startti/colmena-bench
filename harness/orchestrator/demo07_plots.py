"""Render Demo #7 (many-tools needle-in-haystack) charts (PNG) — honest framing.

The hero is the TOKEN WIN, and it GROWS with the tool count: Colmena's lazy tool
loading sends the model a tiny catalog (name + summary) instead of every tool's
full JSON schema, then fetches the one schema it needs via `describe_tool`. At 200
tools that is a fraction of the input tokens of every competitor — and of
colmena-eager (the internal control: same engine, lazy OFF), which proves the
saving comes from the lazy feature, not Colmena in general.

HONEST: on gemini-2.5-flash there is NO accuracy collapse and NO hard-error at
scale — every config stays ~100% accurate even at 200 tools. So the claim is "same
result for a fraction of the tokens at scale", NOT "competitors fail". At small
tool counts (~5) lazy gives no benefit (the catalog ≈ the schemas).

Input:  runs/demo07/summary.json (list of per-(config,n_tools,difficulty) dicts)
Output: runs/demo07/plots/*.png

Charts (per difficulty present in the data):
  tokens_vs_tools_<diff>.png  — HERO: input tokens (LOG y) vs #tools, line/config
  accuracy_vs_tools_<diff>.png — answer_acc (0–1.05) vs #tools, line/config
And one overall:
  tokens_at_200_bar.png — bar of tokens_in_mean per config at n_tools=200, hard
                          (the punchline); colmena-lazy green, ratio annotated.

Reads whatever subset of the grid is present (skips a facet gracefully if empty).

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
    """Tool count for a row. The full-sweep schema uses ``n_tools``; the current
    small-grid summary uses ``count``. Accept either."""
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


def tokens_vs_tools(rows: list[dict], diff: str, outdir: Path) -> "Path | None":
    """HERO: input tokens (LOG y) vs #tools, one line per config, for `diff`."""
    facet = [r for r in rows if r.get("difficulty") == diff]
    if not facet:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for cfg in _configs_present(facet):
        xs, ys = _series(facet, cfg, "tokens_in_mean")
        if not xs:
            continue
        ax.plot(xs, ys, color=_color(cfg), label=cfg, **_style(cfg))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_yscale("log")
    ax.set_xlabel("Number of tools (1 correct + N-1 distractors)")
    ax.set_ylabel("Input tokens (mean, provider-authoritative) — log scale")
    ax.set_title(
        f"Lazy tool loading: same result, a fraction of the tokens at scale "
        f"({diff})\n"
        "colmena-lazy (green) sends a catalog, not every schema; the gap grows "
        "with #tools",
        fontsize=9.5)
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    out = outdir / f"tokens_vs_tools_{diff}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def accuracy_vs_tools(rows: list[dict], diff: str, outdir: Path) -> "Path | None":
    """answer_acc (0–1.05) vs #tools, one line per config, for `diff`.

    Honest: on gemini-2.5-flash these all sit near 1.0 — the win is tokens, not
    accuracy. If the full grid reveals a difficulty-dependent drop, it will show.
    """
    facet = [r for r in rows if r.get("difficulty") == diff]
    if not facet:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for cfg in _configs_present(facet):
        xs, ys = _series(facet, cfg, "answer_acc")
        if not xs:
            continue
        ax.plot(xs, ys, color=_color(cfg), label=cfg, **_style(cfg))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Number of tools (1 correct + N-1 distractors)")
    ax.set_ylabel("Answer accuracy (0–1)")
    ax.set_title(
        f"Accuracy holds at scale — token savings cost no accuracy ({diff})\n"
        "honest: on gemini-2.5-flash all configs stay ~1.0 even at 200 tools",
        fontsize=9.5)
    ax.legend(fontsize=7, loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = outdir / f"accuracy_vs_tools_{diff}.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def tokens_at_200_bar(rows: list[dict], outdir: Path) -> "Path | None":
    """Punchline bar: tokens_in_mean per config at n_tools=200, difficulty=hard.

    colmena-lazy green; annotate the ratio vs the CHEAPEST competitor (a fair,
    conservative framing — we compare to the best non-Colmena, not the worst).
    """
    facet = [r for r in rows
             if _ntools(r) == 200 and r.get("difficulty") == "hard"
             and r.get("tokens_in_mean") is not None]
    if not facet:
        return None
    by = {r["config"]: r["tokens_in_mean"] for r in facet}
    names = [c for c in _configs_present(facet)]
    vals = [by[c] for c in names]

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [_color(c) for c in names]
    bars = ax.bar(names, vals, color=colors)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f}",
                ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Input tokens at 200 tools (mean, hard)")
    ax.set_title("The punchline: input tokens at 200 tools (hard)",
                 fontsize=11)
    ax.tick_params(axis="x", labelrotation=20)
    ax.grid(axis="y", alpha=0.3)

    # ratio vs the cheapest NON-colmena competitor (conservative)
    lazy_v = by.get(LAZY)
    competitors = {c: v for c, v in by.items()
                   if c not in (LAZY, EAGER)}
    if lazy_v and competitors:
        best_comp_name = min(competitors, key=competitors.get)
        best_comp_v = competitors[best_comp_name]
        ratio = best_comp_v / lazy_v if lazy_v else 0
        ax.text(0.98, 0.95,
                f"colmena-lazy ≈ {lazy_v:,.0f} tok\n"
                f"cheapest competitor ({best_comp_name}) ≈ {best_comp_v:,.0f} tok\n"
                f"→ {ratio:.1f}× fewer input tokens",
                transform=ax.transAxes, ha="right", va="top", fontsize=8,
                bbox=dict(boxstyle="round", fc="#eafaf0", ec=C_LAZY))
    fig.tight_layout()
    out = outdir / "tokens_at_200_bar.png"
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
    difficulties = sorted({r.get("difficulty") for r in rows if r.get("difficulty")})
    for diff in difficulties:
        for fn in (tokens_vs_tools, accuracy_vs_tools):
            try:
                out = fn(rows, diff, outdir)
                if out:
                    written.append(out)
                    print(f"  ok: {fn.__name__}({diff}) -> {out}")
                else:
                    print(f"  skip: {fn.__name__}({diff}) — no rows")
            except Exception as e:  # noqa: BLE001
                print(f"  FAIL {fn.__name__}({diff}): {type(e).__name__}: {e}")
    try:
        out = tokens_at_200_bar(rows, outdir)
        if out:
            written.append(out)
            print(f"  ok: tokens_at_200_bar -> {out}")
        else:
            print("  skip: tokens_at_200_bar — no n_tools=200/hard rows")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL tokens_at_200_bar: {type(e).__name__}: {e}")

    print(f"plots -> {outdir}  ({len(written)} written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
