"""Demo #9 — knowledge-pack corpus generator + reference functions + scorer.

SINGLE SOURCE OF TRUTH: each core pack holds a Python `facts` table that BOTH
(a) renders the markdown reference tree on disk AND (b) drives the reference
function that computes the ground-truth answer. Markdown and answer key cannot
drift. Distractor packs are templated bulk to inflate the library to M packs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Leaf:
    """A reference file in a pack's tree. May declare nested children."""
    name: str
    description: str                      # frontmatter description (catalog-visible)
    body: str                            # markdown body
    children: dict[str, "Leaf"] = field(default_factory=dict)


@dataclass
class CorePack:
    name: str                            # == directory name == frontmatter name
    description: str                     # SKILL.md catalog description (when to / not to use)
    overview: str                        # SKILL.md body
    references: dict[str, Leaf]          # top-level reference files
    reference_fn: Callable[[pd.DataFrame, dict], float]


# ---------------------------------------------------------------------------
# Pack 1: tax-by-region  (rule: net revenue is reported EX-VAT; rate is regional)
# ---------------------------------------------------------------------------
# Non-default rule: without the pack a model reports GROSS revenue (includes VAT)
# or guesses a flat rate -> wrong number. With the pack it divides by (1+rate)
# using the country's specific rate from references/<region>.md.

TAX_RATES = {  # SINGLE SOURCE OF TRUTH for both render + reference_fn
    # EU
    "DE": 0.19, "FR": 0.20, "ES": 0.21, "IT": 0.22, "NL": 0.21,
    # LATAM
    "BR": 0.17, "MX": 0.16, "AR": 0.21, "CO": 0.19, "CL": 0.19,
    # APAC
    "JP": 0.10, "AU": 0.10, "IN": 0.18, "SG": 0.09, "KR": 0.10,
}
_TAX_REGIONS = {
    "eu": ["DE", "FR", "ES", "IT", "NL"],
    "latam": ["BR", "MX", "AR", "CO", "CL"],
    "apac": ["JP", "AU", "IN", "SG", "KR"],
}


def _render_rate_table(codes: list[str]) -> str:
    rows = "\n".join(f"| {c} | {int(TAX_RATES[c]*100)}% |" for c in codes)
    return f"| country | vat_rate |\n|---|---|\n{rows}\n"


def _tax_reference_fn(df: pd.DataFrame, params: dict) -> float:
    country = params["country"]
    sub = df[(df["country"] == country) & (df["status"] == params.get("status", "shipped"))]
    gross = float((sub["quantity"].astype(float) * sub["unit_price_usd"].astype(float)).sum())
    rate = TAX_RATES[country]
    return round(gross / (1.0 + rate), 2)


_TAX_PACK = CorePack(
    name="tax-by-region",
    description=(
        "Use when a question asks for net revenue EX-VAT / ex-tax, or applies a "
        "country VAT/GST rate. NOT for gross revenue or for non-tax questions."
    ),
    overview=(
        "# Tax by region\n\n"
        "Reported **net revenue is always EX-VAT**: divide gross (quantity x "
        "unit_price_usd) by (1 + vat_rate). Rates are country-specific. For rate "
        "tables load reference `rates` then navigate to `rates/eu`, `rates/latam`, "
        "or `rates/apac`. For special cases load `edge-cases` (children: `b2b`, "
        "`digital-goods`).\n"
    ),
    references={
        "rates": Leaf(
            name="rates",
            description="Regional VAT/GST rate tables. Children: eu, latam, apac.",
            body="# Regional rates\n\nSee `rates/eu`, `rates/latam`, and `rates/apac`.\n",
            children={
                "eu": Leaf(
                    name="eu",
                    description="VAT rates for EU countries (DE, FR, ES, IT, NL).",
                    body="# EU VAT rates\n\n" + _render_rate_table(_TAX_REGIONS["eu"]),
                ),
                "latam": Leaf(
                    name="latam",
                    description="VAT/IVA rates for LATAM (BR, MX, AR, CO, CL).",
                    body="# LATAM rates\n\n" + _render_rate_table(_TAX_REGIONS["latam"]),
                ),
                "apac": Leaf(
                    name="apac",
                    description="GST/consumption-tax rates for APAC (JP, AU, IN, SG, KR).",
                    body="# APAC rates\n\n" + _render_rate_table(_TAX_REGIONS["apac"]),
                ),
            },
        ),
        "edge-cases": Leaf(
            name="edge-cases",
            description="B2B reverse-charge and digital-goods exceptions. Children: b2b, digital-goods.",
            body="# Tax edge cases\n\nSee `edge-cases/b2b` and `edge-cases/digital-goods`.\n",
            children={
                "b2b": Leaf("b2b", "Reverse-charge rule for B2B intra-EU sales.",
                            "# B2B reverse charge\n\nIntra-EU B2B sales are zero-rated; the buyer self-accounts.\n"),
                "digital-goods": Leaf("digital-goods", "Digital-goods VAT is charged at the buyer's country rate.",
                                      "# Digital goods\n\nDigital goods use the destination-country rate.\n"),
            },
        ),
    },
    reference_fn=_tax_reference_fn,
)

CORE_PACKS: dict[str, CorePack] = {
    "tax-by-region": _TAX_PACK,
}


# ---------------------------------------------------------------------------
# Rendering: pack object -> {relpath: markdown content} with frontmatter
# ---------------------------------------------------------------------------

def _yaml_dq(s: str) -> str:
    """Double-quoted YAML scalar (safe for colons, #, etc.)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _frontmatter(name: str, description: str, child_refs: list[Leaf]) -> str:
    lines = ["---", f"name: {name}", f"description: {_yaml_dq(description)}"]
    if child_refs:
        lines.append("references:")
        for c in child_refs:
            lines.append(f"  - name: {c.name}")
            lines.append(f"    description: {_yaml_dq(c.description)}")
    lines.append("---\n")
    return "\n".join(lines)


def _render_leaf(rel_parent: str, key: str, leaf: Leaf, out: dict[str, str]) -> None:
    rel = f"{rel_parent}/{key}.md" if rel_parent else f"references/{key}.md"
    children = list(leaf.children.values())
    out[rel] = _frontmatter(leaf.name, leaf.description, children) + leaf.body
    base = rel[: -len(".md")]  # nested children live under references/<key>/<child>.md
    for ck, cl in leaf.children.items():
        _render_leaf(base, ck, cl, out)


def render_pack(pack: CorePack) -> dict[str, str]:
    """Return {relpath: content} for the whole pack tree (SKILL.md + references/*)."""
    out: dict[str, str] = {}
    top = list(pack.references.values())
    out["SKILL.md"] = _frontmatter(pack.name, pack.description, top) + pack.overview
    for key, leaf in pack.references.items():
        _render_leaf("", key, leaf, out)
    return out
