"""Demo #9 — knowledge-pack corpus generator + reference functions + scorer.

SINGLE SOURCE OF TRUTH: each core pack holds a Python `facts` table that BOTH
(a) renders the markdown reference tree on disk AND (b) drives the reference
function that computes the ground-truth answer. Markdown and answer key cannot
drift. Distractor packs are templated bulk to inflate the library to M packs.
"""
from __future__ import annotations

import hashlib
import re
import shutil
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

# ---------------------------------------------------------------------------
# Pack 2: returns-and-refunds
# ---------------------------------------------------------------------------
# Non-default rule: orders with status=='refunded' are NOT revenue. Net revenue
# counts SHIPPED orders only, per channel. Without the pack a model sums all
# rows (or includes refunded/delivered) -> a different, plausible number.
# Each channel has a refund-window-days policy (drives the rendered leaf table).

REFUND_WINDOW_DAYS = {  # SINGLE SOURCE OF TRUTH: per-channel refund window
    "web": 30, "store": 14, "mobile": 30, "phone": 21,
}
_REFUND_CHANNEL_GROUPS = {
    "online": ["web", "mobile"],
    "offline": ["store", "phone"],
}


def _render_window_table(channels: list[str]) -> str:
    rows = "\n".join(f"| {c} | {REFUND_WINDOW_DAYS[c]} |" for c in channels)
    return f"| channel | refund_window_days |\n|---|---|\n{rows}\n"


def _returns_reference_fn(df, params):
    sub = df[(df["status"] == "shipped") & (df["channel"] == params["channel"])]
    return round(float((sub["quantity"].astype(float) * sub["unit_price_usd"].astype(float)).sum()), 2)


_RETURNS_PACK = CorePack(
    name="returns-and-refunds",
    description=(
        "Use when a question asks for net revenue that EXCLUDES refunds/returns, "
        "or references a refund window, per channel. NOT for gross revenue that "
        "includes refunded orders, and NOT for tax/fee questions."
    ),
    overview=(
        "# Returns and refunds\n\n"
        "Orders with **status == 'refunded' are NOT revenue** and must be "
        "excluded. Net revenue counts **shipped orders only** (quantity x "
        "unit_price_usd), summed per channel. Refund-window policy is "
        "channel-specific. For window tables load reference `windows` then "
        "navigate to `windows/online` or `windows/offline`.\n"
    ),
    references={
        "windows": Leaf(
            name="windows",
            description="Per-channel refund-window-days tables. Children: online, offline.",
            body="# Refund windows\n\nSee `windows/online` and `windows/offline`.\n",
            children={
                "online": Leaf(
                    name="online",
                    description="Refund windows for online channels (web, mobile).",
                    body="# Online refund windows\n\n" + _render_window_table(_REFUND_CHANNEL_GROUPS["online"]),
                ),
                "offline": Leaf(
                    name="offline",
                    description="Refund windows for offline channels (store, phone).",
                    body="# Offline refund windows\n\n" + _render_window_table(_REFUND_CHANNEL_GROUPS["offline"]),
                ),
            },
        ),
    },
    reference_fn=_returns_reference_fn,
)


# ---------------------------------------------------------------------------
# Pack 3: revenue-recognition
# ---------------------------------------------------------------------------
# Non-default rule: recognized revenue is NET of a category-specific platform
# fee. Without the pack a model reports gross -> plausibly wrong by the fee.

PLATFORM_FEES = {  # SINGLE SOURCE OF TRUTH: per-category platform fee
    "electronics": 0.08, "apparel": 0.12, "home": 0.10, "grocery": 0.04,
    "beauty": 0.11, "books": 0.06, "toys": 0.09,
}
_FEE_CATEGORY_GROUPS = {
    "hardgoods": ["electronics", "home", "toys", "books"],
    "consumables": ["apparel", "grocery", "beauty"],
}


def _render_fee_table(categories: list[str]) -> str:
    rows = "\n".join(f"| {c} | {int(PLATFORM_FEES[c]*100)}% |" for c in categories)
    return f"| product_category | platform_fee |\n|---|---|\n{rows}\n"


def _revrec_reference_fn(df, params):
    fee = PLATFORM_FEES[params["category"]]
    sub = df[(df["status"] == "shipped") & (df["product_category"] == params["category"])]
    gross = float((sub["quantity"].astype(float) * sub["unit_price_usd"].astype(float)).sum())
    return round(gross * (1 - fee), 2)


_REVREC_PACK = CorePack(
    name="revenue-recognition",
    description=(
        "Use when a question asks for recognized/net revenue after the platform "
        "fee for a product category. NOT for gross revenue and NOT for VAT, "
        "processor, or shipping questions."
    ),
    overview=(
        "# Revenue recognition\n\n"
        "Recognized revenue is **net of a category-specific platform fee**: "
        "recognized = gross (quantity x unit_price_usd) x (1 - platform_fee), "
        "over **shipped orders only**. Fees vary by product_category. For fee "
        "tables load reference `fees` then navigate to `fees/hardgoods` or "
        "`fees/consumables`.\n"
    ),
    references={
        "fees": Leaf(
            name="fees",
            description="Per-category platform-fee tables. Children: hardgoods, consumables.",
            body="# Platform fees\n\nSee `fees/hardgoods` and `fees/consumables`.\n",
            children={
                "hardgoods": Leaf(
                    name="hardgoods",
                    description="Platform fees for hard goods (electronics, home, toys, books).",
                    body="# Hard-goods fees\n\n" + _render_fee_table(_FEE_CATEGORY_GROUPS["hardgoods"]),
                ),
                "consumables": Leaf(
                    name="consumables",
                    description="Platform fees for consumables (apparel, grocery, beauty).",
                    body="# Consumables fees\n\n" + _render_fee_table(_FEE_CATEGORY_GROUPS["consumables"]),
                ),
            },
        ),
    },
    reference_fn=_revrec_reference_fn,
)


# ---------------------------------------------------------------------------
# Pack 4: discount-and-promo
# ---------------------------------------------------------------------------
# Non-default rule: stored discount_pct is a DISPLAY discount; the BILLABLE
# discount is capped per channel. Without the pack a model applies the raw
# discount_pct -> a plausibly different (lower) net.

DISCOUNT_CAPS = {  # SINGLE SOURCE OF TRUTH: per-channel billable discount cap
    "web": 0.30, "store": 0.20, "wholesale": 0.50, "mobile": 0.35, "phone": 0.25,
}
_DISCOUNT_CHANNEL_GROUPS = {
    "direct": ["web", "mobile"],
    "assisted": ["store", "phone"],
}


def _render_cap_table(channels: list[str]) -> str:
    rows = "\n".join(f"| {c} | {int(DISCOUNT_CAPS[c]*100)}% |" for c in channels)
    return f"| channel | discount_cap |\n|---|---|\n{rows}\n"


def _discount_reference_fn(df, params):
    cap = DISCOUNT_CAPS[params["channel"]]
    sub = df[(df["status"] == "shipped") & (df["channel"] == params["channel"])].copy()
    eff = sub["discount_pct"].astype(float).clip(upper=cap)
    net = sub["quantity"].astype(float) * sub["unit_price_usd"].astype(float) * (1 - eff)
    return round(float(net.sum()), 2)


_DISCOUNT_PACK = CorePack(
    name="discount-and-promo",
    description=(
        "Use when a question asks for net revenue after discounts where the "
        "stored discount_pct must be CAPPED per channel. NOT for applying the "
        "raw discount_pct, and NOT for tax/fee/shipping questions."
    ),
    overview=(
        "# Discounts and promotions\n\n"
        "The stored `discount_pct` is a **display discount**; the **billable "
        "discount is capped per channel**. Clip discount_pct to the channel cap, "
        "then net = quantity x unit_price_usd x (1 - capped_discount), over "
        "**shipped orders only**. For cap tables load reference `caps` then "
        "navigate to `caps/direct` or `caps/assisted`.\n"
    ),
    references={
        "caps": Leaf(
            name="caps",
            description="Per-channel billable-discount-cap tables. Children: direct, assisted.",
            body="# Discount caps\n\nSee `caps/direct` and `caps/assisted`.\n",
            children={
                "direct": Leaf(
                    name="direct",
                    description="Discount caps for direct channels (web, mobile).",
                    body="# Direct-channel caps\n\n" + _render_cap_table(_DISCOUNT_CHANNEL_GROUPS["direct"]),
                ),
                "assisted": Leaf(
                    name="assisted",
                    description="Discount caps for assisted channels (store, phone).",
                    body="# Assisted-channel caps\n\n" + _render_cap_table(_DISCOUNT_CHANNEL_GROUPS["assisted"]),
                ),
            },
        ),
    },
    reference_fn=_discount_reference_fn,
)


# ---------------------------------------------------------------------------
# Pack 5: payment-method-fees
# ---------------------------------------------------------------------------
# Non-default rule: subtract a processor fee per payment_method. Without the
# pack a model reports gross -> plausibly wrong by the processor fee.

PROCESSOR_FEES = {  # SINGLE SOURCE OF TRUTH: per-method processor fee
    "card": 0.029, "paypal": 0.034, "bank_transfer": 0.008, "crypto": 0.015,
    "cash": 0.000, "transfer": 0.008, "wallet": 0.020,
}
_PROCESSOR_METHOD_GROUPS = {
    "electronic": ["card", "wallet", "paypal", "crypto"],
    "manual": ["cash", "transfer", "bank_transfer"],
}


def _render_processor_table(methods: list[str]) -> str:
    rows = "\n".join(f"| {m} | {PROCESSOR_FEES[m]*100:g}% |" for m in methods)
    return f"| payment_method | processor_fee |\n|---|---|\n{rows}\n"


def _payment_reference_fn(df, params):
    fee = PROCESSOR_FEES[params["payment_method"]]
    sub = df[(df["status"] == "shipped") & (df["payment_method"] == params["payment_method"])]
    gross = float((sub["quantity"].astype(float) * sub["unit_price_usd"].astype(float)).sum())
    return round(gross * (1 - fee), 2)


_PAYMENT_PACK = CorePack(
    name="payment-method-fees",
    description=(
        "Use when a question asks for net revenue after the payment-processor "
        "fee for a payment_method. NOT for gross revenue and NOT for VAT, "
        "platform-fee, or shipping questions."
    ),
    overview=(
        "# Payment-method fees\n\n"
        "Net settlement is **gross minus a processor fee that depends on "
        "payment_method**: net = gross (quantity x unit_price_usd) x "
        "(1 - processor_fee), over **shipped orders only**. For fee tables load "
        "reference `processors` then navigate to `processors/electronic` or "
        "`processors/manual`.\n"
    ),
    references={
        "processors": Leaf(
            name="processors",
            description="Per-method processor-fee tables. Children: electronic, manual.",
            body="# Processor fees\n\nSee `processors/electronic` and `processors/manual`.\n",
            children={
                "electronic": Leaf(
                    name="electronic",
                    description="Processor fees for electronic methods (card, wallet, paypal, crypto).",
                    body="# Electronic-method fees\n\n" + _render_processor_table(_PROCESSOR_METHOD_GROUPS["electronic"]),
                ),
                "manual": Leaf(
                    name="manual",
                    description="Processor fees for manual methods (cash, transfer, bank_transfer).",
                    body="# Manual-method fees\n\n" + _render_processor_table(_PROCESSOR_METHOD_GROUPS["manual"]),
                ),
            },
        ),
    },
    reference_fn=_payment_reference_fn,
)


# ---------------------------------------------------------------------------
# Pack 6: shipping-cost-allocation
# ---------------------------------------------------------------------------
# Non-default rule: net contribution = revenue MINUS shipping_usd, shipped only,
# per country. Without the pack a model reports revenue ignoring shipping cost.
# Each region has a free-shipping threshold (drives the rendered leaf table).

FREE_SHIP_THRESHOLD = {  # SINGLE SOURCE OF TRUTH: per-country free-shipping threshold (USD)
    # na
    "US": 50,
    # emea
    "ES": 40,
    # latam
    "BR": 60, "MX": 55, "AR": 65, "CO": 60, "CL": 60, "PE": 70,
}
_SHIP_REGIONS = {
    "na": ["US"],
    "emea": ["ES"],
    "latam": ["BR", "MX", "AR", "CO", "CL", "PE"],
}


def _render_threshold_table(codes: list[str]) -> str:
    rows = "\n".join(f"| {c} | ${FREE_SHIP_THRESHOLD[c]} |" for c in codes)
    return f"| country | free_ship_threshold_usd |\n|---|---|\n{rows}\n"


def _shipping_reference_fn(df, params):
    sub = df[(df["status"] == "shipped") & (df["country"] == params["country"])]
    rev = sub["quantity"].astype(float) * sub["unit_price_usd"].astype(float)
    return round(float((rev - sub["shipping_usd"].astype(float)).sum()), 2)


_SHIPPING_PACK = CorePack(
    name="shipping-cost-allocation",
    description=(
        "Use when a question asks for net contribution = revenue minus shipping "
        "cost, per country, or references a free-shipping threshold. NOT for "
        "gross revenue that ignores shipping, and NOT for tax/fee questions."
    ),
    overview=(
        "# Shipping-cost allocation\n\n"
        "Net contribution **subtracts shipping_usd from revenue**: contribution "
        "= (quantity x unit_price_usd) - shipping_usd, summed over **shipped "
        "orders only**, per country. Free-shipping thresholds are regional. For "
        "threshold tables load reference `thresholds` then navigate to "
        "`thresholds/na`, `thresholds/emea`, or `thresholds/latam`.\n"
    ),
    references={
        "thresholds": Leaf(
            name="thresholds",
            description="Per-region free-shipping-threshold tables. Children: na, emea, latam.",
            body="# Free-shipping thresholds\n\nSee `thresholds/na`, `thresholds/emea`, and `thresholds/latam`.\n",
            children={
                "na": Leaf(
                    name="na",
                    description="Free-shipping thresholds for North America (US).",
                    body="# NA thresholds\n\n" + _render_threshold_table(_SHIP_REGIONS["na"]),
                ),
                "emea": Leaf(
                    name="emea",
                    description="Free-shipping thresholds for EMEA (ES).",
                    body="# EMEA thresholds\n\n" + _render_threshold_table(_SHIP_REGIONS["emea"]),
                ),
                "latam": Leaf(
                    name="latam",
                    description="Free-shipping thresholds for LATAM (BR, MX, AR, CO, CL, PE).",
                    body="# LATAM thresholds\n\n" + _render_threshold_table(_SHIP_REGIONS["latam"]),
                ),
            },
        ),
    },
    reference_fn=_shipping_reference_fn,
)


CORE_PACKS: dict[str, CorePack] = {
    "tax-by-region": _TAX_PACK,
    "returns-and-refunds": _RETURNS_PACK,
    "revenue-recognition": _REVREC_PACK,
    "discount-and-promo": _DISCOUNT_PACK,
    "payment-method-fees": _PAYMENT_PACK,
    "shipping-cost-allocation": _SHIPPING_PACK,
}


# ---------------------------------------------------------------------------
# Question bank: natural-language questions bound to the specific reference LEAF
# holding the fact each one needs. Different questions hit different tree
# branches so Colmena's nested navigation is exercised.
# ---------------------------------------------------------------------------

@dataclass
class Question:
    id: str
    pack: str
    text: str                 # natural language; never names the pack mechanic explicitly
    params: dict
    leaf_path: str            # e.g. "rates/eu" — where the needed fact lives


def leaf_path_exists(pack_name: str, leaf_path: str) -> bool:
    node = CORE_PACKS[pack_name].references
    parts = leaf_path.split("/")
    cur = node.get(parts[0])
    for p in parts[1:]:
        if cur is None:
            return False
        cur = cur.children.get(p)
    return cur is not None


QUESTION_BANK: list[Question] = [
    # --- tax-by-region (param: country, status; leaves rates/eu, rates/latam) ---
    Question("tax_es", "tax-by-region",
             "What is the net revenue reported ex-VAT for shipped orders to ES?",
             {"country": "ES", "status": "shipped"}, "rates/eu"),
    Question("tax_br", "tax-by-region",
             "What is the net revenue (ex-tax) recognized on shipped orders to BR?",
             {"country": "BR", "status": "shipped"}, "rates/latam"),
    Question("tax_mx", "tax-by-region",
             "For shipped orders to MX, what is the revenue net of value-added tax?",
             {"country": "MX", "status": "shipped"}, "rates/latam"),

    # --- returns-and-refunds (param: channel; leaves windows/online, windows/offline) ---
    Question("returns_web", "returns-and-refunds",
             "What is the net revenue from web orders, excluding anything that was returned?",
             {"channel": "web"}, "windows/online"),
    Question("returns_mobile", "returns-and-refunds",
             "How much net revenue did the mobile channel keep after backing out returned orders?",
             {"channel": "mobile"}, "windows/online"),
    Question("returns_store", "returns-and-refunds",
             "What net revenue did the store channel retain once returned orders are removed?",
             {"channel": "store"}, "windows/offline"),

    # --- revenue-recognition (param: category; leaves fees/hardgoods, fees/consumables) ---
    Question("revrec_electronics", "revenue-recognition",
             "What is the recognized revenue for shipped electronics orders after the marketplace commission is deducted?",
             {"category": "electronics"}, "fees/hardgoods"),
    Question("revrec_books", "revenue-recognition",
             "How much revenue is recognized on books once the platform's share is deducted?",
             {"category": "books"}, "fees/hardgoods"),
    Question("revrec_beauty", "revenue-recognition",
             "What is the net recognized revenue for beauty products after platform charges?",
             {"category": "beauty"}, "fees/consumables"),

    # --- discount-and-promo (param: channel; leaves caps/direct, caps/assisted) ---
    Question("discount_web", "discount-and-promo",
             "What is the net revenue for web orders after the allowable promotional reduction is applied?",
             {"channel": "web"}, "caps/direct"),
    Question("discount_mobile", "discount-and-promo",
             "For the mobile channel, what is the net revenue once permitted promo reductions are applied?",
             {"channel": "mobile"}, "caps/direct"),
    Question("discount_phone", "discount-and-promo",
             "What is the revenue for shipped phone-channel orders after applying the allowed promotional reduction?",
             {"channel": "phone"}, "caps/assisted"),

    # --- payment-method-fees (param: payment_method; leaves processors/electronic, processors/manual) ---
    Question("payment_card", "payment-method-fees",
             "What is the net settlement on card orders after the processor's cut?",
             {"payment_method": "card"}, "processors/electronic"),
    Question("payment_wallet", "payment-method-fees",
             "How much do wallet orders settle to net of the processing charge?",
             {"payment_method": "wallet"}, "processors/electronic"),
    Question("payment_transfer", "payment-method-fees",
             "What is the net amount settled on shipped orders paid by bank transfer, after the processor's deduction?",
             {"payment_method": "transfer"}, "processors/manual"),

    # --- shipping-cost-allocation (param: country; leaves thresholds/na, emea, latam) ---
    Question("shipping_us", "shipping-cost-allocation",
             "What is the net contribution from US orders after shipping cost is subtracted?",
             {"country": "US"}, "thresholds/na"),
    Question("shipping_es", "shipping-cost-allocation",
             "For ES orders, what is the contribution once shipping expense is netted out?",
             {"country": "ES"}, "thresholds/emea"),
    Question("shipping_br", "shipping-cost-allocation",
             "What is the net contribution on BR orders after deducting the cost to ship them?",
             {"country": "BR"}, "thresholds/latam"),
]


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


# ---------------------------------------------------------------------------
# Distractor packs + corpus materialization (Task 4)
# ---------------------------------------------------------------------------
# Distractor packs are templated bulk: realistic NESTED reference trees for
# non-core domains that no question targets. They exist purely to inflate the
# library to M packs and add retrieval confusion — the whole point of the demo
# is that naive prompt-stuffing the corpus is expensive (>=150k tokens at M=50).

_DISTRACTOR_DOMAINS = [
    "cohort-definitions", "channel-attribution", "fx-and-currency", "cogs-and-margin",
    "fiscal-calendar", "chargebacks-and-fraud", "inventory-valuation", "loyalty-points",
    "subscription-billing", "gift-cards", "marketplace-commissions", "warranty-claims",
    "price-matching", "bundle-pricing", "tax-exemptions", "credit-memos", "dunning",
    "deferred-revenue", "regional-rounding", "settlement-timing",
]

_DISTRACTOR_ROWS = 26  # tuned so the 50-pack corpus clears the 150k-token floor (~190k)


def _distractor_pack_files(name: str, rng_seed: str) -> dict[str, str]:
    """A realistic, bulky NESTED tree for a non-core domain. No reference_fn.
    Deterministic per (name, seed). Tune row counts so the 50-pack corpus clears
    the 150k-token density floor."""
    h = hashlib.sha256(rng_seed.encode()).hexdigest()
    regions = ["na", "emea", "apac", "latam"]
    # SKILL.md declares the 4 regional references as children
    files = {
        "SKILL.md": _frontmatter(
            name, f"Reference knowledge for {name.replace('-', ' ')}.",
            [Leaf(r, f"{name} parameters for region {r}.", "") for r in regions],
        ) + f"# {name}\n\nDomain rules and parameter tables for {name}. "
            f"Load the regional reference for specifics.\n",
    }
    for i, r in enumerate(regions):
        rows = "\n".join(
            f"| param_{j} | {int(h[(i + j) % len(h)], 16) * 7 % 100}% | "
            f"applies to {name} {r} param {j}; review at period close and reconcile "
            f"against the {r} schedule of record before posting any adjustment |"
            for j in range(_DISTRACTOR_ROWS)
        )
        files[f"references/{r}.md"] = _frontmatter(
            r, f"{name} parameter table for {r}.", []
        ) + (f"# {name} — {r}\n\nParameter schedule for {r}. Apply the value that "
             f"matches the row key.\n\n| parameter | value | notes |\n|---|---|---|\n{rows}\n")
    return files


def _write_files(pack_dir: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        fp = pack_dir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)


def materialize_corpus(out_dir: str, pack_count: int, seed: int) -> str:
    """Write `pack_count` packs to out_dir: core packs first (always present when
    pack_count >= number of core packs), the remainder filled with deterministic
    distractor packs. Returns out_dir. Idempotent (clears out_dir first)."""
    import random
    root = Path(out_dir)
    sentinel = root / ".colmena_corpus"
    if root.exists():
        # Safety: only clear a dir that is empty or that we previously created
        # (marked with the sentinel). Refuse anything else so a bad path can't
        # silently delete user data.
        if any(root.iterdir()) and not sentinel.exists():
            raise ValueError(
                f"refusing to clear {root!s}: not empty and missing .colmena_corpus "
                f"sentinel (not a corpus dir created by materialize_corpus)"
            )
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / ".colmena_corpus").write_text("demo09 corpus\n")

    core_items = list(CORE_PACKS.items())
    if pack_count <= len(core_items):
        for name, pack in core_items[:pack_count]:
            _write_files(root / name, render_pack(pack))
        return out_dir

    for name, pack in core_items:
        _write_files(root / name, render_pack(pack))
    n_distract = pack_count - len(core_items)
    rng = random.Random(f"{pack_count}-{seed}")
    pool = list(_DISTRACTOR_DOMAINS)
    rng.shuffle(pool)
    chosen = list(pool[:n_distract])
    while len(chosen) < n_distract:  # deterministic suffixing if pool too small
        base = pool[len(chosen) % len(pool)]
        chosen.append(f"{base}-{len(chosen)}")
    for name in chosen:
        _write_files(root / name, _distractor_pack_files(name, f"{name}-{seed}"))
    return out_dir


def corpus_token_estimate(corpus_dir: str) -> int:
    """~4 chars/token estimate over every .md file in the corpus."""
    total = sum(len(p.read_text()) for p in Path(corpus_dir).rglob("*.md"))
    return total // 4


# ---------------------------------------------------------------------------
# Scorer (Task 5)
# ---------------------------------------------------------------------------

def _parse_number(text):
    """First numeric value in a string, tolerant of commas, currency symbols,
    surrounding prose, signs, and scientific notation. Returns None if no number
    is present (the honesty rule: unparseable -> not measured, never 0.0)."""
    if text is None:
        return None
    cleaned = re.sub(r"[,$€£]", "", str(text))
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][+-]?\d+)?", cleaned)
    return float(m.group()) if m else None


def score_skill_answer(question: "Question", produced: str, df: "pd.DataFrame") -> dict:
    """Grade a produced answer against the reference function.

    Returns a dict with keys:
      correct: True / False, or None when the answer is empty/unparseable
               (NOT measured — never silently 0, per the Demo #8 honesty fix).
      want:    the ground-truth float.
      got:     the parsed float, or None.
    """
    want = CORE_PACKS[question.pack].reference_fn(df, question.params)
    got = _parse_number(produced)
    if got is None:
        return {"correct": None, "want": want, "got": None}
    ok = abs(got - want) <= 0.02 * max(1.0, abs(want))
    return {"correct": bool(ok), "want": want, "got": got}


# ---------------------------------------------------------------------------
# Naive prompt builder (Task 5)
# ---------------------------------------------------------------------------

def build_naive_system_prompt(corpus_dir: str) -> str:
    """Concatenate EVERY pack's full markdown tree — the naive arm's strategy.

    Produces a single system-prompt string containing all pack content. At
    M=50 this exceeds 150k tokens, making it the expensive baseline against
    which Colmena's progressive-load arm is compared.
    """
    parts = [
        "You are a finance analyst. The full policy manual follows. "
        "Apply the correct policy to answer. Manual:\n"
    ]
    for md in sorted(Path(corpus_dir).rglob("*.md")):
        parts.append(f"\n\n===== {md.relative_to(corpus_dir)} =====\n{md.read_text()}")
    return "".join(parts)
