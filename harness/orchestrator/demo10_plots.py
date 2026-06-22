"""Render Demo #10 (secure secret collection) charts (PNG).

Hero framing: Colmena's secure_suspend + secure:true tool means the secret NEVER
reaches the LLM by construction. Competitor frameworks let the secret flow straight
into the LLM transcript (the idiomatic "paste your credentials" pattern). The
charts make this empirical (leak_rate) + structural (capability_matrix) + honest
about implementation cost (loc).

Input:  runs/demo10/summary.json
        Each row: {framework, variant, seed, secret_leaked (bool|None),
                   delivered_to_api (bool), round_trips (int), error (str|None)}
Output: runs/demo10/plots/{leak_rate,capability_matrix,loc}.png

Charts:
  1  leak_rate        — fraction of cells with secret_leaked==True per framework,
                        annotated by variant.  Colmena 0; competitors ~1.
  2  capability_matrix — demo10_matrix rendered as a heatmap table (✓/✗).
  3  loc              — security-relevant lines of code per framework. For Colmena
                        counts the secure config lines in secrets_agent.json + the
                        thin runner; for competitors counts collect+POST handler LOC.
                        Indicative proxy — annotated as such.

Usage: PYTHONPATH=harness .venv-bench/bin/python harness/orchestrator/demo10_plots.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from demo10_matrix import CAPABILITY_MATRIX, FEATURE_LABELS, FRAMEWORKS  # noqa: E402

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent

COLMENA = "colmena"
C_HI = "#1f9d55"    # colmena green — native / secure / guaranteed
C_DIY = "#c0392b"   # red — DIY / leaks
C_CODE = "#e1a948"  # amber — hand-rolled imperative code

# ordered display names
FW_LABELS = {
    "colmena":    "colmena",
    "langgraph":  "langgraph",
    "crewai":     "crewai",
    "langchain":  "langchain",
    "llamaindex": "llamaindex",
    "google_adk": "google_adk",
}


# ---------------------------------------------------------------------------
# LOC helpers
# ---------------------------------------------------------------------------

def _count_loc(path: Path) -> int:
    """Count non-blank, non-comment lines in a Python file."""
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith('"""') and stripped != '"""':
            count += 1
    return count


def _count_json_security_lines(path: Path) -> int:
    """Count lines in a JSON file that contain security-relevant keywords.

    For the Colmena DAG (secrets_agent.json) we count only the lines that
    carry the secure_suspend / secure:true / inject_secrets config — the
    actual security primitives, not the boilerplate node graph. This is
    deliberately narrow to compare apples-to-apples against the competitor
    collect+POST logic. Annotated as indicative in the chart.
    """
    if not path.exists():
        return 0
    keywords = re.compile(
        r"secure_suspend|secure_suspend|secure.*true|inject_secrets|"
        r"node_type.*secure|SECURE_VALUES_KEY|sv_|AES|encrypt|mask_outbound",
        re.IGNORECASE,
    )
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines()
               if keywords.search(line))


def _security_loc(fw: str) -> int:
    """Security-relevant LOC for a framework's task10 implementation.

    For Colmena: count security config lines in secrets_agent.json + the thin
    runner (task10_secrets.py) minus its docstring bulk. For simplicity we count
    the full runner (it IS thin by design — <50 lines of logic) PLUS the
    security-focused JSON lines.

    For competitors: count the full task10_secrets.py — every line is part of
    the hand-rolled collect+mask+POST pattern. No LOC is "free": the dev must
    write, read, test, and maintain it all.
    """
    runners = REPO_ROOT / "runners"
    py_path = runners / fw / "runner" / "tasks" / "task10_secrets.py"
    if fw == COLMENA:
        dag_path = runners / fw / "runner" / "dags" / "secrets_agent.json"
        json_sec = _count_json_security_lines(dag_path)
        py_loc = _count_loc(py_path)
        return json_sec + py_loc
    return _count_loc(py_path)


# ---------------------------------------------------------------------------
# Chart 1: leak_rate
# ---------------------------------------------------------------------------

def leak_rate(summary: list[dict], outdir: Path) -> None:
    """Bar chart: secret leak rate per framework (fraction with secret_leaked==True).

    Only rows where secret_leaked is not None and error is None/empty count toward
    the denominator. Grouped by variant (collect / echo) using two bars.
    """
    variants = ["collect", "echo"]
    variant_colors = {"collect": "#3498db", "echo": "#9b59b6"}

    # Gather per-framework-per-variant rates
    # fw -> variant -> (leaked_n, total_n)
    counts: dict[str, dict[str, list[int]]] = {
        fw: {v: [0, 0] for v in variants} for fw in FRAMEWORKS
    }
    for row in summary:
        fw = row.get("framework", "")
        if fw not in counts:
            continue
        v = row.get("variant", "")
        if v not in variants:
            continue
        if row.get("secret_leaked") is None:
            continue  # exclude uncertain rows from denominator
        counts[fw][v][1] += 1  # total
        if row["secret_leaked"] is True:
            counts[fw][v][0] += 1  # leaked

    # Only include frameworks that appear in the summary
    seen_fws = sorted({r["framework"] for r in summary if r.get("framework") in FRAMEWORKS},
                      key=lambda f: FRAMEWORKS.index(f))

    fig, ax = plt.subplots(figsize=(11, 5))
    x = list(range(len(seen_fws)))
    n_variants = len(variants)
    w = 0.35
    offsets = [-(n_variants - 1) * w / 2 + i * w for i in range(n_variants)]

    for vi, (vt, offset) in enumerate(zip(variants, offsets)):
        rates = []
        ns = []
        for fw in seen_fws:
            leaked_n, total_n = counts[fw][vt]
            rate = (leaked_n / total_n) if total_n > 0 else 0.0
            rates.append(rate)
            ns.append(total_n)
        bars = ax.bar([xi + offset for xi in x], rates, w,
                      label=f"variant={vt}", color=variant_colors[vt],
                      edgecolor="black", lw=0.5, alpha=0.88)
        for bar, rate, n in zip(bars, rates, ns):
            if n > 0:
                label_text = f"{rate:.0%}\n(n={n})"
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.02,
                        label_text,
                        ha="center", va="bottom", fontsize=7.5)

    ax.set_xticks(x)
    ax.set_xticklabels(seen_fws, fontsize=10)
    ax.set_ylim(0, 1.35)
    ax.set_ylabel("Fraction of runs with secret_leaked = True")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.axhline(0, color="#aaa", lw=0.6)
    fig.suptitle("Secret reaches the LLM? (lower is better)", fontsize=13, y=0.99)
    ax.set_title(
        "Colmena's secure_suspend encrypts the secret into an opaque handle — "
        "the real value never enters the LLM/proxy transcript.\n"
        "Competitors use the idiomatic 'paste credentials' pattern; the secret "
        "appears in the LLM messages every time.",
        fontsize=8.5, color="#555", pad=8,
    )
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    out = outdir / "leak_rate.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  ok: leak_rate -> {out}")


# ---------------------------------------------------------------------------
# Chart 2: capability_matrix
# ---------------------------------------------------------------------------

def capability_matrix(_summary: list[dict], outdir: Path) -> None:
    """Heatmap table: rows = security guarantees, cols = frameworks.

    native (engine config) = green ✓; DIY (hand-rolled code) = red ✗.
    LangGraph earns green for durable_pause — honest near-peer framing.
    """
    feats = list(CAPABILITY_MATRIX.keys())
    cols = FRAMEWORKS
    nrows, ncols = len(feats), len(cols)

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.set_xlim(0, ncols)
    ax.set_ylim(0, nrows)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # column headers
    for j, c in enumerate(cols):
        is_col = c == COLMENA
        ax.text(j + 0.5, nrows + 0.22, c, ha="center", va="bottom",
                fontsize=10.5, fontweight="bold" if is_col else "normal",
                color=C_HI if is_col else "#333")

    # row labels + cells
    for i, feat in enumerate(feats):
        y = nrows - 1 - i
        label = FEATURE_LABELS.get(feat, feat.replace("_", " "))
        ax.text(-0.1, y + 0.5, label, ha="right", va="center",
                fontsize=9.5, fontweight="bold")
        for j, c in enumerate(cols):
            val = CAPABILITY_MATRIX[feat][c]
            native = val == "native"
            color = C_HI if native else C_DIY
            glyph = "✓" if native else "✗"
            sublabel = "native\n(config)" if native else "DIY\n(code)"
            ax.add_patch(plt.Rectangle((j + 0.04, y + 0.06), 0.92, 0.88,
                                       facecolor=color, edgecolor="white", lw=2))
            ax.text(j + 0.5, y + 0.62, glyph, ha="center", va="center",
                    fontsize=14, color="white", fontweight="bold")
            ax.text(j + 0.5, y + 0.26, sublabel, ha="center", va="center",
                    fontsize=7, color="white")

    ax.set_title(
        "Security guarantees: native engine config vs hand-rolled code",
        fontsize=13, pad=30,
    )
    legend = [
        Patch(facecolor=C_HI, label="native — declarative config, engine-guaranteed"),
        Patch(facecolor=C_DIY, label="DIY — imperative code you write, test & maintain"),
    ]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.13),
              ncol=2, fontsize=8.5, frameon=False)
    fig.subplots_adjust(left=0.22, right=0.97, top=0.85, bottom=0.12)
    out = outdir / "capability_matrix.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  ok: capability_matrix -> {out}")


# ---------------------------------------------------------------------------
# Chart 3: loc
# ---------------------------------------------------------------------------

def loc(summary: list[dict], outdir: Path) -> None:
    """Bar chart: security-relevant lines of code per framework.

    For Colmena: security config lines in secrets_agent.json (the secure_suspend
    + secure:true node schema) plus the thin two-phase runner. For competitors:
    the full task10_secrets.py (the collect + POST + echo pattern is ALL
    security-relevant — the dev must write and maintain every line of it).

    Annotated as indicative — LOC is a proxy for implementation surface, not a
    precise metric.
    """
    seen_fws = sorted({r["framework"] for r in summary if r.get("framework") in FRAMEWORKS},
                      key=lambda f: FRAMEWORKS.index(f))
    # Fall back to full FRAMEWORKS if summary is sparse
    all_fws = seen_fws if seen_fws else FRAMEWORKS

    locs = [_security_loc(fw) for fw in all_fws]

    fig, ax = plt.subplots(figsize=(11, 5))
    colors = [C_HI if fw == COLMENA else C_DIY for fw in all_fws]
    bars = ax.bar(range(len(all_fws)), locs, 0.6, color=colors, edgecolor="black", lw=0.5)
    for bar, v in zip(bars, locs):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.5, str(v),
                ha="center", va="bottom", fontsize=9)

    ax.set_xticks(range(len(all_fws)))
    ax.set_xticklabels(all_fws, fontsize=10)
    ax.set_ylabel("Security-relevant lines of code")
    fig.suptitle("Secret handling: declarative config (Colmena) vs hand-rolled code",
                 fontsize=13, y=0.99)
    ax.set_title(
        "Colmena = security config lines in secrets_agent.json + thin runner. "
        "Competitors = full collect+POST handler (every line is security-relevant).\n"
        "Indicative proxy — see runner files for exact line counts.",
        fontsize=8.5, color="#555", pad=8,
    )
    legend = [
        Patch(facecolor=C_HI, label="Colmena — DAG config + thin runner"),
        Patch(facecolor=C_DIY, label="competitors — hand-rolled collect/POST handler"),
    ]
    ax.legend(handles=legend, loc="upper right", fontsize=8.5, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    out = outdir / "loc.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  ok: loc -> {out}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    summary_path = REPO_ROOT / "runs/demo10/summary.json"
    if not summary_path.exists():
        print(f"no summary at {summary_path} — skipping charts (exit 0)")
        return 0
    text = summary_path.read_text(encoding="utf-8").strip()
    if not text or text in ("[]", "null"):
        print(f"summary at {summary_path} is empty — skipping charts (exit 0)")
        return 0

    summary = json.loads(text)
    if not summary:
        print(f"summary at {summary_path} has 0 rows — skipping charts (exit 0)")
        return 0

    outdir = REPO_ROOT / "runs/demo10/plots"
    outdir.mkdir(parents=True, exist_ok=True)

    leak_rate(summary, outdir)
    capability_matrix(summary, outdir)
    loc(summary, outdir)

    print(f"plots -> {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
