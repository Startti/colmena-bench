#!/usr/bin/env python
"""Generate Figure 1: per-turn input-token curves for three arms of the
context-tax analyst session (see paper/sections/05-context.tex).

Data is copied verbatim from .superpowers/sdd/task-4-brief.md.

Usage:
    .venv-bench/bin/python paper/figures/make_context_curves.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- Data (per-turn input tokens, 10 turns) --------------------------------

TURNS = list(range(1, 11))

ADK_DEFAULT = [3351, 3838, 19224, 27952, 26367, 75196, 48830, 48878, 120341, 71395]
ADK_ARTIFACTS_SCRUB = [3948, 4590, 1651, 5096, 1003, 2161, 1142, 5642, 1314, 1357]
COLMENA = [4901, 4056, 3502, 4398, 1833, 5213, 2955, 5682, 4250, 2296]

CHART_TURNS = (3, 6, 9)

# --- Style -------------------------------------------------------------

plt.rcParams.update(
    {
        "font.size": 11,
        "font.family": "serif",
        "axes.labelsize": 12,
        "axes.titlesize": 12,
        "legend.fontsize": 10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "axes.linewidth": 0.8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

COLOR_ADK_DEFAULT = "#C44E52"
COLOR_ADK_SCRUB = "#4C72B0"
COLOR_COLMENA = "#55A868"


def main() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 3.6))

    # Light vertical guides on the three chart turns so the ADK-default
    # blowups are visually anchored to the tool-call events that cause them.
    for t in CHART_TURNS:
        ax.axvline(t, color="0.85", linewidth=8, zorder=0)

    ax.plot(
        TURNS,
        ADK_DEFAULT,
        color=COLOR_ADK_DEFAULT,
        marker="o",
        markersize=4,
        linewidth=1.6,
        label="Google ADK (default)",
        zorder=3,
    )
    ax.plot(
        TURNS,
        ADK_ARTIFACTS_SCRUB,
        color=COLOR_ADK_SCRUB,
        marker="s",
        markersize=4,
        linewidth=1.6,
        label="Google ADK (artifacts_scrub)",
        zorder=3,
    )
    ax.plot(
        TURNS,
        COLMENA,
        color=COLOR_COLMENA,
        marker="^",
        markersize=4,
        linewidth=1.6,
        label="Colmena",
        zorder=3,
    )

    # Mark the chart-turn spikes on the ADK-default curve explicitly.
    for t in CHART_TURNS:
        y = ADK_DEFAULT[t - 1]
        ax.annotate(
            f"{y:,}",
            xy=(t, y),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            color=COLOR_ADK_DEFAULT,
        )

    ax.set_xlabel("Turn")
    ax.set_ylabel("Input tokens")
    ax.set_xticks(TURNS)
    ax.set_xlim(0.5, 10.5)
    ax.set_ylim(0, max(ADK_DEFAULT) * 1.15)
    ax.yaxis.set_major_formatter(lambda x, _: f"{int(x):,}")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(loc="upper left", frameon=False)

    fig.tight_layout()

    out_path = Path(__file__).resolve().parent / "context_curves.pdf"
    fig.savefig(out_path)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
