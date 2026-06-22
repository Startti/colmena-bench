"""Deterministic orders_synthetic dataset generator.

Used by Task 4 (CSV killer demo) and other tasks that need a realistic-but-
controlled tabular dataset.

Determinism contract:
- Same `--size` and same `--seed` ⇒ byte-identical CSV.
- Row `i` is the same across sizes (the larger size is just more rows).
  This lets us compare token-vs-rows scaling without changing the data
  shape underneath the framework. See METHODOLOGY §7.

Usage:
    python data/orders_synthetic/generator.py --size S --out seeds/S.csv
    python data/orders_synthetic/generator.py --size M --out seeds/M.csv
    python data/orders_synthetic/generator.py --size L --out seeds/L.csv
    python data/orders_synthetic/generator.py --size XL --out seeds/XL.csv

Sizes (rows):
    S=500, M=5_000, L=50_000, XL=500_000  (XL is generated on demand for T25)

Schema: data/orders_synthetic/schema.json.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

SIZES = {"S": 500, "M": 5_000, "L": 50_000, "XL": 500_000}

COUNTRIES = ["MX", "AR", "CL", "CO", "PE", "BR", "US", "ES"]
COUNTRY_WEIGHTS = [0.22, 0.18, 0.12, 0.10, 0.08, 0.18, 0.07, 0.05]

CHANNELS = ["web", "mobile", "phone", "store"]
CHANNEL_WEIGHTS = [0.45, 0.40, 0.05, 0.10]

CATEGORIES = ["electronics", "apparel", "home", "books", "grocery", "beauty", "toys"]
CATEGORY_PRICE_RANGES = {
    "electronics": (29.0, 2500.0),
    "apparel": (9.0, 250.0),
    "home": (5.0, 800.0),
    "books": (3.0, 60.0),
    "grocery": (0.99, 80.0),
    "beauty": (4.0, 220.0),
    "toys": (3.0, 180.0),
}

STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled", "refunded"]
STATUS_WEIGHTS = [0.05, 0.10, 0.15, 0.55, 0.10, 0.05]

PAYMENT_METHODS = ["card", "cash", "transfer", "wallet"]
PAYMENT_WEIGHTS = [0.55, 0.10, 0.20, 0.15]

FIRST_DATE = date(2024, 1, 1)
LAST_DATE = date(2025, 12, 31)
DATE_SPAN_DAYS = (LAST_DATE - FIRST_DATE).days

NUM_CUSTOMERS = 50_000   # ~10% repeat rate at L; rare repeat at S
NUM_PRODUCTS = 5_000     # spread across categories

FIELDS = [
    "order_id",
    "customer_id",
    "order_date",
    "country",
    "channel",
    "product_id",
    "product_category",
    "quantity",
    "unit_price_usd",
    "discount_pct",
    "shipping_usd",
    "status",
    "payment_method",
]


def _gen_row(i: int, rng: random.Random) -> list:
    """Generate row index `i` using a *per-row* seed derived from `i`.

    Critical: per-row seeding gives us the invariant that row `i` is the same
    across sizes. If we let one Random walk through all rows, the row at
    index 200 in S would not equal the row at index 200 in L.
    """
    r = random.Random(rng.getstate())  # base rng holds master seed
    r.seed((rng.random() * 1e18 + i).__hash__())
    # Simpler & still deterministic:
    r = random.Random((i, rng.getstate()[1][0]))

    country = r.choices(COUNTRIES, weights=COUNTRY_WEIGHTS, k=1)[0]
    channel = r.choices(CHANNELS, weights=CHANNEL_WEIGHTS, k=1)[0]
    category = r.choice(CATEGORIES)
    lo, hi = CATEGORY_PRICE_RANGES[category]
    unit_price = round(r.uniform(lo, hi), 2)
    quantity = r.randint(1, 20)
    discount_pct = round(r.choices([0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50],
                                   weights=[0.50, 0.18, 0.15, 0.08, 0.05, 0.03, 0.01], k=1)[0], 2)
    shipping = 0.0 if channel == "store" else round(r.uniform(0.0, 25.0), 2)
    if unit_price > 500 and channel != "store":
        shipping = round(r.uniform(15.0, 75.0), 2)
    status = r.choices(STATUSES, weights=STATUS_WEIGHTS, k=1)[0]
    payment = r.choices(PAYMENT_METHODS, weights=PAYMENT_WEIGHTS, k=1)[0]

    order_id = f"O{i:09d}"
    customer_id = f"C{r.randint(0, NUM_CUSTOMERS - 1):06d}"
    product_id = f"P{r.randint(0, NUM_PRODUCTS - 1):05d}"
    day_offset = r.randint(0, DATE_SPAN_DAYS)
    order_date = (FIRST_DATE + timedelta(days=day_offset)).isoformat()

    return [
        order_id,
        customer_id,
        order_date,
        country,
        channel,
        product_id,
        category,
        quantity,
        unit_price,
        discount_pct,
        shipping,
        status,
        payment,
    ]


def generate(n_rows: int, seed: int, out_path: Path) -> None:
    rng = random.Random(seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for i in range(n_rows):
            w.writerow(_gen_row(i, rng))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="orders_synthetic generator")
    p.add_argument("--size", choices=list(SIZES.keys()), required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    generate(SIZES[args.size], args.seed, args.out)
    print(f"wrote {SIZES[args.size]} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
