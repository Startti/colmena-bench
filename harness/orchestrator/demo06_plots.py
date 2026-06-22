"""Render Demo #4 (refund agent) charts (PNG) — honest production-hardening framing.

The hero is NOT "fewer lines" — total LOC is comparable across frameworks. The
hero is: production hardening (durable HITL, critic-retry, outbound secret
masking) is GUARANTEED by Colmena's engine via declarative config flags, vs
HAND-ROLLED imperative safety code in the competitors that you can get wrong
(and a naive variant — omitting the manual scrub — provably leaks the secret).

Input:  runs/demo06/summary.json (list of per-framework dicts)
Output: runs/demo06/plots/*.png

Charts:
  1 loc_code_vs_config  — code LOC (imperative, maintained) vs config LOC
                          (declarative, engine-run). LOC is comparable — honest.
  2 capability_matrix    — native (config) vs DIY (code) heatmap. CENTERPIECE.
  3 masking_guarantee    — HERO. engine-guaranteed masking vs manual scrub that
                          leaks if forgotten (proven counterfactual).

Usage: python demo06_plots.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from demo06_matrix import CAPABILITY_MATRIX, FRAMEWORKS  # noqa: E402

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent

COLMENA = "colmena"
C_HI = "#1f9d55"      # colmena green — native / declarative config (the hero)
C_CODE = "#e1a948"    # amber — imperative code you maintain
C_DIY = "#c0392b"     # red — DIY / hand-rolled / can-leak

# Frameworks for which the NAIVE (no-scrub) variant provably leaks the secret: the
# tool result carrying the secret reaches the LLM unless the dev hand-writes the
# outbound scrub. This is exactly every framework whose `masking` cell is DIY —
# i.e. all 5 non-Colmena frameworks (including langgraph: native graph/HITL/retry
# but still DIY masking). Derived from the matrix so it generalizes to N frameworks.
NAIVE_LEAK = {fw for fw, val in CAPABILITY_MATRIX["masking"].items() if val == "DIY"}


def _by_fw(summary: list[dict]) -> dict[str, dict]:
    return {r["framework"]: r for r in summary}


def loc_code_vs_config(summary, outdir):
    """Grouped bars per framework: imperative code LOC vs declarative config LOC.

    HONEST: does NOT imply Colmena has fewer lines. The point is WHERE the lines
    live — Colmena's are declarative config the engine runs; competitors' are
    imperative safety logic you write and maintain.
    """
    by = _by_fw(summary)
    names = [f for f in FRAMEWORKS if f in by]
    code = [by[n]["code_loc"] for n in names]
    config = [by[n]["config_loc"] for n in names]

    fig, ax = plt.subplots(figsize=(11, 5))
    x = range(len(names))
    w = 0.38
    b_code = ax.bar([i - w / 2 for i in x], code, w,
                    label="imperative code (you maintain)", color=C_CODE)
    b_cfg = ax.bar([i + w / 2 for i in x], config, w,
                   label="declarative config (engine runs)", color=C_HI)
    for bars, vals in ((b_code, code), (b_cfg, config)):
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, str(v),
                    ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x)); ax.set_xticklabels(names)
    ax.set_ylabel("Lines of code")
    fig.suptitle("Same agent, same guarantees — where the lines live",
                 fontsize=13, y=0.99)
    ax.set_title(
        "LOC is comparable; Colmena's lines are declarative config the engine "
        "runs,\ncompetitors' are imperative safety logic you write and maintain",
        fontsize=8.5, color="#555", pad=8)
    ax.legend(loc="upper right", fontsize=8.5)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(outdir / "loc_code_vs_config.png", dpi=150)
    plt.close(fig)


def capability_matrix(summary, outdir):
    """Heatmap table: rows = hardening features, cols = frameworks.

    native (engine config) = green; DIY (hand-rolled code) = red. CENTERPIECE.
    """
    feats = list(CAPABILITY_MATRIX.keys())
    cols = FRAMEWORKS
    nrows, ncols = len(feats), len(cols)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.set_xlim(0, ncols); ax.set_ylim(0, nrows)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # column headers
    for j, c in enumerate(cols):
        is_col = c == COLMENA
        ax.text(j + 0.5, nrows + 0.18, c, ha="center", va="bottom",
                fontsize=11, fontweight="bold" if is_col else "normal",
                color=C_HI if is_col else "#333")
    # row labels (top feature drawn at top → reverse y)
    for i, feat in enumerate(feats):
        y = nrows - 1 - i
        ax.text(-0.1, y + 0.5, feat.replace("_", " "), ha="right", va="center",
                fontsize=10, fontweight="bold")
        for j, c in enumerate(cols):
            val = CAPABILITY_MATRIX[feat][c]
            native = val == "native"
            color = C_HI if native else C_DIY
            label = "native\n(config)" if native else "DIY\n(code)"
            ax.add_patch(plt.Rectangle((j + 0.04, y + 0.06), 0.92, 0.88,
                                       facecolor=color, edgecolor="white", lw=2))
            ax.text(j + 0.5, y + 0.5, label, ha="center", va="center",
                    fontsize=9.5, color="white", fontweight="bold")

    ax.set_title("Production hardening: native (config) vs hand-rolled (code)",
                 fontsize=13, pad=26)
    legend = [Patch(facecolor=C_HI, label="native — declarative config, engine-guaranteed"),
              Patch(facecolor=C_DIY, label="DIY — imperative code you write, test & maintain")]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.13),
              ncol=2, fontsize=8.5, frameon=False)
    fig.subplots_adjust(left=0.16, right=0.97, top=0.86, bottom=0.12)
    fig.savefig(outdir / "capability_matrix.png", dpi=150)
    plt.close(fig)


def masking_guarantee(summary, outdir):
    """HERO chart: outbound secret masking is engine-GUARANTEED in Colmena and
    MANUAL (leaks if forgotten) in the Python competitors.

    Honest: every HARDENED impl scores secret_leaked=False (from the data). But
    the NAIVE variant of the 3 Python frameworks — omitting the hand-written
    scrub — provably leaks (a tool result carrying the secret reaches the LLM).
    Colmena cannot leak: the engine masks outbound on a `secure: true` tool.
    """
    by = _by_fw(summary)
    names = [f for f in FRAMEWORKS if f in by]

    fig, ax = plt.subplots(figsize=(11, 5))
    x = range(len(names))
    bars = []
    for i, n in enumerate(names):
        guaranteed = n == COLMENA
        color = C_HI if guaranteed else C_CODE
        bars.append(ax.bar(i, 1.0, 0.6, color=color, edgecolor="black", lw=0.6))

    ax.set_xlim(-0.6, len(names) - 0.4)
    ax.set_xticks(list(x)); ax.set_xticklabels(names)
    ax.set_ylim(0, 1.35)
    ax.set_yticks([])
    ax.set_ylabel("")
    fig.suptitle("Outbound secret masking: engine-guaranteed vs hand-rolled",
                 fontsize=13, y=0.99)
    ax.set_title(
        "All hardened impls score secret_leaked = False. But for the Python "
        "frameworks that is\nTRUE ONLY because the dev hand-wrote the scrub — "
        "omit it and the naive variant leaks.",
        fontsize=8.5, color="#555", pad=8)

    for i, n in enumerate(names):
        leaked = by[n]["secret_leaked"]
        if n == COLMENA:
            ax.text(i, 0.5, "GUARANTEED\nSAFE", ha="center", va="center",
                    fontsize=10, color="white", fontweight="bold")
            ax.text(i, 1.04, "engine `secure: true`\ncannot leak by construction",
                    ha="center", va="bottom", fontsize=8, color=C_HI,
                    fontweight="bold")
        else:
            ax.text(i, 0.5, "safe ONLY because\nwe hand-wrote\nthe scrub",
                    ha="center", va="center", fontsize=9, color="#5a4a1a",
                    fontweight="bold")
            note = "naive variant\nLEAKS (omit scrub)" if n in NAIVE_LEAK else ""
            if note:
                ax.text(i, 1.04, note, ha="center", va="bottom", fontsize=8,
                        color=C_DIY, fontweight="bold")
        # factual data label at base
        ax.text(i, 0.04, f"hardened:\nsecret_leaked={leaked}", ha="center",
                va="bottom", fontsize=7.5, color="white")

    legend = [Patch(facecolor=C_HI, label="Colmena — engine-guaranteed (declarative)"),
              Patch(facecolor=C_CODE, label="competitors — manual scrub (leaks if forgotten)")]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.16),
              ncol=2, fontsize=8.5, frameon=False)
    ax.text(0.5, -0.24,
            "Note: the leak is a demonstrated counterfactual of the NAIVE variant, "
            "not a measured failure of the hardened impls.",
            transform=ax.transAxes, ha="center", va="top", fontsize=7.5,
            color="#888", style="italic")
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    fig.subplots_adjust(left=0.04, right=0.96, top=0.82, bottom=0.20)
    fig.savefig(outdir / "masking_guarantee.png", dpi=150)
    plt.close(fig)


def main() -> int:
    summary_path = REPO_ROOT / "runs/demo06/summary.json"
    if not summary_path.exists():
        print(f"no summary at {summary_path}")
        return 1
    summary = json.loads(summary_path.read_text())
    outdir = REPO_ROOT / "runs/demo06/plots"
    outdir.mkdir(parents=True, exist_ok=True)
    for fn in (loc_code_vs_config, capability_matrix, masking_guarantee):
        fn(summary, outdir)
        print(f"  ok: {fn.__name__} -> {outdir / (fn.__name__ + '.png')}")
    print(f"plots -> {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
