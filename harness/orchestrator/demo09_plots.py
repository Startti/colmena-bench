"""Render Demo #9 (Skills / progressive knowledge loading) charts (PNG).

The premise: a question must be answered from a knowledge corpus of N "packs"
(insurance policy bundles). Three arms approach the same corpus differently:

  - colmena : declarative skills + load_skill — the model navigates a 3-level
              tree and pulls in only the relevant skill(s). Tokens stay flat as
              the corpus grows.
  - naive   : the 5 competitor frameworks stuff the WHOLE corpus into the prompt.
              Tokens explode linearly with corpus size.
  - rag     : llamaindex + langchain embed the corpus into a vector store and
              retrieve top-k. Tokens stay low but accuracy hinges on a flat
              retrieval hit (no tree navigation), and it needs vector-DB infra.

Hero: tokens_vs_packs — naive explodes, colmena + rag stay flat; accuracy and
navigation-vs-retrieval explain why colmena holds up.

Input:  runs/demo09/summary.json  (list of per-(framework,arm,pack,seed,question)
        row dicts produced by demo_skills_run.py)
Output: runs/demo09/plots/*.png

Charts:
  1 tokens_vs_packs          — HERO: mean llm_tokens_in vs pack_count (LOG y), per arm.
  2 accuracy_vs_packs        — mean correct (%) vs pack_count, per arm.
  3 retrieval_vs_navigation  — colmena "loaded >=1 skill" vs rag "retrieval hit".
  4 cost_at_50_bar           — mean USD/question at pack_count=50, per arm.
  5 capability_matrix        — honest feature matrix (arms x capabilities).

Robust: missing/empty summary -> message + exit 0; sparse arms/pack_counts are
skipped gracefully (single-point lines are still drawn as markers).

Usage: python demo09_plots.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent

PACK_COUNTS = [5, 20, 50]
ARMS = ["colmena", "naive", "rag"]

# Colors mirror the demo07/08 conventions: colmena green is the hero.
C_COLMENA = "#1f9d55"   # green — the hero
C_NAIVE = "#c0392b"     # red — prompt-stuffing, explodes
C_RAG = "#4e79a7"       # blue — vector retrieval
C_HI = "#1f9d55"        # green — capability ✓ (colmena's win)
C_DIY = "#c0392b"       # red — capability ✗ / infra cost
C_AMBER = "#e1a948"     # amber — partial / contained-but-not-by-colmena
C_GRAY = "#888888"

ARM_COLOR = {"colmena": C_COLMENA, "naive": C_NAIVE, "rag": C_RAG}
ARM_LABEL = {
    "colmena": "colmena (load_skill)",
    "naive": "naive (all-in-prompt)",
    "rag": "rag (vector retrieval)",
}


def _arm_style(arm: str) -> dict:
    if arm == "colmena":
        return {"linewidth": 2.8, "linestyle": "-", "marker": "o", "zorder": 5}
    if arm == "naive":
        return {"linewidth": 2.0, "linestyle": "-", "marker": "s", "zorder": 4}
    return {"linewidth": 2.0, "linestyle": "--", "marker": "^", "zorder": 3}


def _live(rows: list[dict]) -> list[dict]:
    """Rows usable for token/accuracy means (not errored, not skipped)."""
    return [r for r in rows if not r.get("error") and not r.get("skipped")]


def _arms_present(rows: list[dict]) -> list[str]:
    seen = {r.get("arm") for r in rows}
    return [a for a in ARMS if a in seen]


def _packs_present(rows: list[dict]) -> list[int]:
    seen = {r.get("pack_count") for r in rows if r.get("pack_count") is not None}
    ordered = [p for p in PACK_COUNTS if p in seen]
    return ordered + sorted(seen - set(ordered))


def _mean_by_pack(rows: list[dict], arm: str, key: str) -> tuple[list, list]:
    """(x=pack_count, y=mean of `key`) for one arm, over live rows where key is
    a number. Sorted by pack_count."""
    xs, ys = [], []
    for p in _packs_present(rows):
        vals = [r[key] for r in rows
                if r.get("arm") == arm and r.get("pack_count") == p
                and isinstance(r.get(key), (int, float))
                and not isinstance(r.get(key), bool)]
        if vals:
            xs.append(p)
            ys.append(mean(vals))
    return xs, ys


# --------------------------------------------------------------------------- #
# 1. tokens_vs_packs (HERO)
# --------------------------------------------------------------------------- #
def tokens_vs_packs(rows: list[dict], outdir: Path) -> "Path | None":
    live = _live(rows)
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for arm in _arms_present(live):
        xs, ys = _mean_by_pack(live, arm, "llm_tokens_in")
        if not xs:
            continue
        ax.plot(xs, ys, color=ARM_COLOR[arm], label=ARM_LABEL[arm], **_arm_style(arm))
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_yscale("log")
    ax.set_xticks(_packs_present(live) or PACK_COUNTS)
    ax.set_xlabel("Knowledge-corpus size (number of packs)")
    ax.set_ylabel("Context tokens per question — mean llm_tokens_in (log scale)")
    ax.set_title(
        "Context tokens vs knowledge-corpus size\n"
        "all-in-prompt explodes; load_skill + retrieval stay flat",
        fontsize=10)
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    out = outdir / "tokens_vs_packs.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# 2. accuracy_vs_packs
# --------------------------------------------------------------------------- #
def accuracy_vs_packs(rows: list[dict], outdir: Path) -> "Path | None":
    live = _live(rows)
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    for arm in _arms_present(live):
        xs, ys, ns = [], [], []
        for p in _packs_present(live):
            measured = [r["correct"] for r in live
                        if r.get("arm") == arm and r.get("pack_count") == p
                        and isinstance(r.get("correct"), bool)]
            if measured:
                xs.append(p)
                ys.append(100.0 * mean(1.0 if c else 0.0 for c in measured))
                ns.append(len(measured))
        if not xs:
            continue
        ax.plot(xs, ys, color=ARM_COLOR[arm], label=ARM_LABEL[arm], **_arm_style(arm))
        for x, y, n in zip(xs, ys, ns):
            ax.annotate(f"n={n}", (x, y), textcoords="offset points",
                        xytext=(0, 6), ha="center", fontsize=7, color="#666")
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_ylim(0, 105)
    ax.set_xticks(_packs_present(live) or PACK_COUNTS)
    ax.set_xlabel("Knowledge-corpus size (number of packs)")
    ax.set_ylabel("Answer accuracy (% of measured questions)")
    ax.set_title(
        "Answer accuracy vs corpus size\n"
        "correct==null rows are not measured (excluded, never counted as wrong)",
        fontsize=10)
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = outdir / "accuracy_vs_packs.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# 3. retrieval_vs_navigation
# --------------------------------------------------------------------------- #
def retrieval_vs_navigation(rows: list[dict], outdir: Path) -> "Path | None":
    live = _live(rows)
    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False

    # colmena: fraction of rows that loaded >=1 skill
    xs_c, ys_c = [], []
    for p in _packs_present(live):
        rs = [r for r in live if r.get("arm") == "colmena"
              and r.get("pack_count") == p
              and isinstance(r.get("skills_used_count"), (int, float))
              and not isinstance(r.get("skills_used_count"), bool)]
        if rs:
            xs_c.append(p)
            ys_c.append(100.0 * mean(1.0 if r["skills_used_count"] >= 1 else 0.0
                                     for r in rs))
    if xs_c:
        ax.plot(xs_c, ys_c, color=C_COLMENA, label="colmena: loaded ≥1 skill",
                linewidth=2.8, marker="o", zorder=5)
        plotted = True

    # rag: fraction of rows with retrieval_hit == True
    xs_r, ys_r = [], []
    for p in _packs_present(live):
        rs = [r for r in live if r.get("arm") == "rag"
              and r.get("pack_count") == p
              and isinstance(r.get("retrieval_hit"), bool)]
        if rs:
            xs_r.append(p)
            ys_r.append(100.0 * mean(1.0 if r["retrieval_hit"] else 0.0 for r in rs))
    if xs_r:
        ax.plot(xs_r, ys_r, color=C_RAG, label="rag: retrieval hit",
                linewidth=2.0, linestyle="--", marker="^", zorder=3)
        plotted = True

    if not plotted:
        plt.close(fig)
        return None
    ax.set_ylim(0, 105)
    ax.set_xticks(_packs_present(live) or PACK_COUNTS)
    ax.set_xlabel("Knowledge-corpus size (number of packs)")
    ax.set_ylabel("Success rate (%)")
    ax.set_title(
        "Why accuracy diverges: navigation vs flat retrieval\n"
        "colmena navigates a 3-level tree; rag does one flat top-k lookup",
        fontsize=10)
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = outdir / "retrieval_vs_navigation.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# 4. cost_at_50_bar
# --------------------------------------------------------------------------- #
def _gemini_prices() -> tuple[float, float, "float | None"]:
    """(input_per_1m, output_per_1m, embed_per_1m|None) for gemini-2.5-flash."""
    pt = json.loads((HARNESS_DIR / "pricing_table.json").read_text())
    m = pt.get("models", {}).get("gemini-2.5-flash", {})
    inp = m.get("input_per_1m", 0.30)
    out = m.get("output_per_1m", 2.50)
    # An embedding price may live under a dedicated model entry; honor it if present.
    embed = None
    for key in ("gemini-embedding", "text-embedding-004", "embedding"):
        em = pt.get("models", {}).get(key)
        if em and "input_per_1m" in em:
            embed = em["input_per_1m"]
            break
    return inp, out, embed


def cost_at_50_bar(rows: list[dict], outdir: Path) -> "Path | None":
    live = _live(rows)
    packs = _packs_present(live)
    # Prefer 50; fall back to the largest available pack_count for the smoke run.
    target = 50 if 50 in packs else (max(packs) if packs else None)
    if target is None:
        return None
    facet = [r for r in live if r.get("pack_count") == target]
    if not facet:
        return None

    inp_p, out_p, embed_p = _gemini_prices()
    arms = _arms_present(facet)
    if not arms:
        return None

    llm_cost, embed_cost = {}, {}
    for arm in arms:
        rs = [r for r in facet if r.get("arm") == arm]
        tin = [r["llm_tokens_in"] for r in rs
               if isinstance(r.get("llm_tokens_in"), (int, float))]
        tout = [r["llm_tokens_out"] for r in rs
                if isinstance(r.get("llm_tokens_out"), (int, float))]
        llm_cost[arm] = ((mean(tin) if tin else 0.0) * inp_p
                         + (mean(tout) if tout else 0.0) * out_p) / 1e6
        if arm == "rag" and embed_p is not None:
            etok = [r["embed_tokens"] for r in rs
                    if isinstance(r.get("embed_tokens"), (int, float))]
            embed_cost[arm] = (mean(etok) if etok else 0.0) * embed_p / 1e6
        else:
            embed_cost[arm] = 0.0

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [ARM_COLOR[a] for a in arms]
    base = [llm_cost[a] for a in arms]
    bars = ax.bar(range(len(arms)), base, 0.6, color=colors,
                  edgecolor="black", lw=0.6, label="LLM (in+out)")
    # faded stacked embedding segment for rag, when an embedding price exists
    extra = [embed_cost[a] for a in arms]
    if any(extra):
        ax.bar(range(len(arms)), extra, 0.6, bottom=base, color=C_RAG,
               alpha=0.35, edgecolor="black", lw=0.4, label="embeddings (one-time)")
    for i, a in enumerate(arms):
        tot = base[i] + extra[i]
        ax.text(i, tot, f"${tot:.5f}", ha="center", va="bottom", fontsize=8)

    ax.set_xticks(range(len(arms)))
    ax.set_xticklabels([ARM_LABEL[a] for a in arms], fontsize=8)
    ax.set_ylabel("Mean cost per question (USD, gemini-2.5-flash)")
    suffix = "" if target == 50 else f" (largest available: {target})"
    ax.set_title(f"Cost per question at {target} packs{suffix}", fontsize=11)
    if embed_p is None:
        ax.text(0.98, 0.95, "embeddings est. excluded\n(no embedding price in pricing_table)",
                transform=ax.transAxes, ha="right", va="top", fontsize=7.5,
                color="#666", bbox=dict(boxstyle="round", fc="#f4f4f4", ec="#ccc"))
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    out = outdir / "cost_at_50_bar.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# 5. capability_matrix
# --------------------------------------------------------------------------- #
# rows = arms, cols = capabilities. True = ✓ (good), False = ✗ (bad/infra).
_CAP_COLS = [
    "Declarative\n(no infra)",
    "No vector DB /\nembeddings",
    "No prompt-\nstuffing",
    "Tree navigation\n(3-level)",
    "Tokens flat as\ncorpus grows",
]
_CAP_ROWS = {
    "Colmena (load_skill)": [True, True, True, True, True],
    "Naive (all-in-prompt)": [True, True, False, False, False],
    "RAG (vector retrieval)": [False, False, True, False, True],
}


def capability_matrix(rows: list[dict], outdir: Path) -> "Path | None":
    row_names = list(_CAP_ROWS.keys())
    cols = _CAP_COLS
    nrows, ncols = len(row_names), len(cols)

    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.set_xlim(0, ncols)
    ax.set_ylim(0, nrows)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # column headers
    for j, c in enumerate(cols):
        ax.text(j + 0.5, nrows + 0.12, c, ha="center", va="bottom",
                fontsize=9.5, fontweight="bold", color="#333")

    for i, rn in enumerate(row_names):
        y = nrows - 1 - i
        is_colmena = rn.startswith("Colmena")
        ax.text(-0.08, y + 0.5, rn, ha="right", va="center", fontsize=10,
                fontweight="bold",
                color=C_HI if is_colmena else "#333")
        for j, val in enumerate(_CAP_ROWS[rn]):
            color = C_HI if val else C_DIY
            label = "✓" if val else "✗"
            ax.add_patch(plt.Rectangle((j + 0.04, y + 0.06), 0.92, 0.88,
                                       facecolor=color, edgecolor="white", lw=2))
            ax.text(j + 0.5, y + 0.5, label, ha="center", va="center",
                    fontsize=16, color="white", fontweight="bold")

    ax.set_title("Skills / progressive knowledge loading — capability matrix",
                 fontsize=13, pad=26)
    legend = [Patch(facecolor=C_HI, label="✓ capability present"),
              Patch(facecolor=C_DIY, label="✗ absent / requires infra")]
    ax.legend(handles=legend, loc="lower center", bbox_to_anchor=(0.5, -0.16),
              ncol=2, fontsize=8.5, frameon=False)
    fig.subplots_adjust(left=0.20, right=0.97, top=0.82, bottom=0.16)
    out = outdir / "capability_matrix.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
def main() -> int:
    summary_path = REPO_ROOT / "runs/demo09/summary.json"
    if not summary_path.exists():
        print(f"no summary at {summary_path} — nothing to plot (ok)")
        return 0
    try:
        rows = json.loads(summary_path.read_text())
    except json.JSONDecodeError as e:
        print(f"summary not valid JSON ({e}) — nothing to plot (ok)")
        return 0
    if not rows:
        print(f"summary is empty: {summary_path} — nothing to plot (ok)")
        return 0

    outdir = REPO_ROOT / "runs/demo09/plots"
    outdir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for fn in (tokens_vs_packs, accuracy_vs_packs, retrieval_vs_navigation,
               cost_at_50_bar, capability_matrix):
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
