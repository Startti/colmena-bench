"""Render Demo #8 (sandboxed code execution over CSV) charts (PNG).

Hero (dual): (1) SECURITY — Colmena runs model-written pandas in a restricted,
in-process, declarative sandbox; among competitors the result is heterogeneous and
you cannot assume safety (2/5 leak). (2) DX — attaching a CSV and running pandas is
native in Colmena vs a hand-wired specialized component elsewhere. Honest non-claim:
analytics accuracy is ~at parity (not a win).

Input:  runs/demo08/summary.json (list of per-(framework,variant,mode) dicts).
Output: runs/demo08/plots/*.png

Charts:
  1 capability_matrix — DX (native vs DIY) + security (blocked vs leaked) heatmap.
  2 security_probe    — HERO. controlled canary probe per framework (contained vs LEAKED).
  3 analytics_parity  — analytics accuracy by framework (the honest parity axis).

Usage: python demo08_plots.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from demo08_matrix import DX_MATRIX, FRAMEWORKS, security_row  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

C_HI = "#1f9d55"     # green — native / safe / contained (the hero)
C_AMBER = "#e1a948"  # amber — partial / library / docker / server (contained, not by colmena's mechanism)
C_DIY = "#c0392b"    # red — DIY / leaked / unsafe
C_GRAY = "#888888"   # gray — skipped / unknown
COLMENA = "colmena"

# color + short label for a security/DX cell value
_DX_STYLE = {
    "native":  (C_HI, "native"),
    "DIY":     (C_DIY, "DIY"),
    "library": (C_AMBER, "library"),
    "docker":  (C_AMBER, "Docker"),
    "server":  (C_AMBER, "server-side"),
    "no":      (C_DIY, "none"),
}
_SEC_STYLE = {
    "blocked": (C_HI, "contained"),
    "leaked":  (C_DIY, "LEAKED"),
    "skipped": (C_GRAY, "skipped"),
    "error":   (C_GRAY, "error"),
    "?":       (C_GRAY, "n/a"),
}


def _present(summary):
    return [f for f in FRAMEWORKS if any(r.get("framework") == f for r in summary)]


def capability_matrix(summary, outdir):
    sec = security_row(summary)
    feats = list(DX_MATRIX.keys()) + ["blocks_file_read"]
    cols = FRAMEWORKS
    nrows, ncols = len(feats), len(cols)

    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.set_xlim(0, ncols); ax.set_ylim(0, nrows)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    for j, c in enumerate(cols):
        is_col = c == COLMENA
        ax.text(j + 0.5, nrows + 0.18, c, ha="center", va="bottom",
                fontsize=11, fontweight="bold" if is_col else "normal",
                color=C_HI if is_col else "#333")

    pretty = {"native_attach": "attach+pandas\nnative",
              "safe_by_default": "safe by default\n(no opt-in/Docker)",
              "blocks_file_read": "blocks file read\n(canary probe)"}
    for i, feat in enumerate(feats):
        y = nrows - 1 - i
        ax.text(-0.1, y + 0.5, pretty.get(feat, feat), ha="right", va="center",
                fontsize=9.5, fontweight="bold")
        for j, c in enumerate(cols):
            if feat == "blocks_file_read":
                color, label = _SEC_STYLE.get(sec[c], (C_GRAY, sec[c]))
            else:
                color, label = _DX_STYLE.get(DX_MATRIX[feat][c], (C_GRAY, DX_MATRIX[feat][c]))
            ax.add_patch(plt.Rectangle((j + 0.04, y + 0.06), 0.92, 0.88,
                                       facecolor=color, edgecolor="white", lw=2))
            ax.text(j + 0.5, y + 0.5, label, ha="center", va="center",
                    fontsize=9, color="white", fontweight="bold")

    ax.set_title("Sandboxed code execution over a CSV — DX + security",
                 fontsize=13, pad=26)
    legend = [Patch(facecolor=C_HI, label="Colmena's native/declarative/in-process win"),
              Patch(facecolor=C_AMBER, label="contained, but via library / Docker / server (not declarative)"),
              Patch(facecolor=C_DIY, label="DIY wiring / unsandboxed (leaks)")]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.16),
              ncol=3, fontsize=8, frameon=False)
    fig.subplots_adjust(left=0.20, right=0.97, top=0.84, bottom=0.16)
    fig.savefig(outdir / "capability_matrix.png", dpi=150)
    plt.close(fig)


def security_probe(summary, outdir):
    """HERO: controlled canary probe — did the executor refuse open(canary)?"""
    sec = security_row(summary)
    names = _present(summary)
    fig, ax = plt.subplots(figsize=(11, 5))
    for i, n in enumerate(names):
        val = sec.get(n, "?")
        color, _ = _SEC_STYLE.get(val, (C_GRAY, val))
        ax.bar(i, 1.0, 0.6, color=color, edgecolor="black", lw=0.6)
        if val == "blocked":
            txt, sub = "CONTAINED", "sandbox refused\nopen(canary)"
        elif val == "leaked":
            txt, sub = "LEAKED", "exec read the\ncanary token"
        elif val == "skipped":
            txt, sub = "SKIPPED", "Docker not\navailable here"
        else:
            txt, sub = val.upper(), ""
        ax.text(i, 0.5, txt, ha="center", va="center", fontsize=10,
                color="white", fontweight="bold")
        if sub:
            ax.text(i, 1.04, sub, ha="center", va="bottom", fontsize=7.5,
                    color="#555")

    ax.set_xlim(-0.6, len(names) - 0.4)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([("colmena" if n == COLMENA else n) for n in names],
                       fontweight="bold")
    ax.set_ylim(0, 1.4); ax.set_yticks([])
    fig.suptitle("Controlled probe: model code tries to read a planted canary file",
                 fontsize=13, y=0.99)
    ax.set_title(
        "Colmena's restricted in-process sandbox refuses it. Among competitors the "
        "result is heterogeneous:\nraw-exec agents (langchain, langgraph) LEAK; "
        "others contain via library eval / Docker / server-side kernel.",
        fontsize=8.5, color="#555", pad=8)
    legend = [Patch(facecolor=C_HI, label="contained (no leak)"),
              Patch(facecolor=C_DIY, label="LEAKED canary"),
              Patch(facecolor=C_GRAY, label="skipped / n.a.")]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.14),
              ncol=3, fontsize=8.5, frameon=False)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    fig.subplots_adjust(left=0.04, right=0.96, top=0.80, bottom=0.14)
    fig.savefig(outdir / "security_probe.png", dpi=150)
    plt.close(fig)


def analytics_parity(summary, outdir):
    """Honest parity axis: analytics accuracy by framework (mean over variants)."""
    names = _present(summary)
    accs = []
    for n in names:
        vals = [r.get("analytics_acc") for r in summary
                if r.get("framework") == n and r.get("mode") == "analytics"
                and isinstance(r.get("analytics_acc"), (int, float))]
        accs.append(mean(vals) if vals else 0.0)

    fig, ax = plt.subplots(figsize=(11, 5))
    colors = [C_HI if n == COLMENA else C_AMBER for n in names]
    bars = ax.bar(range(len(names)), accs, 0.6, color=colors, edgecolor="black", lw=0.6)
    for b, v in zip(bars, accs):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.2f}",
                ha="center", va="bottom", fontsize=9)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([("colmena" if n == COLMENA else n) for n in names],
                       fontweight="bold")
    ax.set_ylim(0, 1.1); ax.set_ylabel("analytics accuracy (mean over S/M/L)")
    fig.suptitle("Analytics accuracy — the honest parity axis (NOT the win)",
                 fontsize=13, y=0.99)
    ax.set_title("Everyone runs model-written pandas over a preview; accuracy is "
                 "broadly comparable.\nThe win is security + DX, not accuracy or tokens.",
                 fontsize=8.5, color="#555", pad=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(outdir / "analytics_parity.png", dpi=150)
    plt.close(fig)


def main() -> int:
    summary_path = REPO_ROOT / "runs/demo08/summary.json"
    if not summary_path.exists():
        print(f"no summary at {summary_path}")
        return 1
    summary = json.loads(summary_path.read_text())
    outdir = REPO_ROOT / "runs/demo08/plots"
    outdir.mkdir(parents=True, exist_ok=True)
    for fn in (capability_matrix, security_probe, analytics_parity):
        fn(summary, outdir)
        print(f"  ok: {fn.__name__} -> {outdir / (fn.__name__ + '.png')}")
    print(f"plots -> {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
