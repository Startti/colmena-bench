"""Recompute ground_truth.json from seeds/*.csv.

Single source of truth for Task 4 scoring. Run after regenerating seeds:

    python data/orders_synthetic/generator.py --size S --out data/orders_synthetic/seeds/S.csv
    python data/orders_synthetic/compute_ground_truth.py

Reads:  data/orders_synthetic/questions_20.json
        data/orders_synthetic/seeds/{S,M,L}.csv (XL optional)
Writes: data/orders_synthetic/ground_truth.json
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SEEDS = HERE / "seeds"
QUESTIONS_PATH = HERE / "questions_20.json"
OUT_PATH = HERE / "ground_truth.json"


def _round(x: float, n: int = 4) -> float:
    return float(round(x, n))


def _net_value(row) -> float:
    return float(row["quantity"]) * float(row["unit_price_usd"]) * (1.0 - float(row["discount_pct"]))


def compute_for(df: pd.DataFrame) -> dict:
    out: dict = {}

    out["Q01"] = int(len(df))
    out["Q02"] = int(df["customer_id"].nunique())
    out["Q03"] = _round(float(df["unit_price_usd"].max()), 2)
    out["Q04"] = int((df["status"] == "cancelled").sum())
    out["Q05"] = str(df["order_date"].min())

    gross = (df["quantity"] * df["unit_price_usd"])
    by_country = gross.groupby(df["country"]).sum().sort_values(ascending=False)
    out["Q06"] = {k: _round(float(v), 2) for k, v in by_country.items()}

    avg_disc = df.groupby("channel")["discount_pct"].mean().sort_index()
    out["Q07"] = {k: _round(float(v)) for k, v in avg_disc.items()}

    by_cat = df["product_category"].value_counts().sort_values(ascending=False)
    out["Q08"] = {k: int(v) for k, v in by_cat.items()}

    out["Q09"] = _round(float(df.loc[df["channel"] == "store", "shipping_usd"].sum()), 2)
    out["Q10"] = _round(float((df["payment_method"] == "card").mean()))

    qty_by_product = df.groupby("product_id")["quantity"].sum().sort_values(ascending=False)
    out["Q11"] = list(qty_by_product.head(5).index)

    out["Q12"] = int((pd.to_datetime(df["order_date"]).dt.year == 2025).sum())

    aov = (df["quantity"] * df["unit_price_usd"]).groupby(df["channel"]).mean().sort_index()
    out["Q13"] = {k: _round(float(v), 2) for k, v in aov.items()}

    active = df["status"].isin(["paid", "shipped", "delivered"])
    net_rev = (df.loc[active, "quantity"] * df.loc[active, "unit_price_usd"]
               * (1.0 - df.loc[active, "discount_pct"])
               + df.loc[active, "shipping_usd"]).sum()
    out["Q14"] = _round(float(net_rev), 2)

    qty_country_cat = df.groupby(["country", "product_category"])["quantity"].sum().reset_index()
    top_per_country: dict = {}
    for country, grp in qty_country_cat.groupby("country"):
        winner = grp.sort_values("quantity", ascending=False).iloc[0]
        top_per_country[country] = winner["product_category"]
    out["Q15"] = top_per_country

    ym = pd.to_datetime(df["order_date"]).dt.to_period("M").astype(str)
    by_month = ym.value_counts().sort_index()
    out["Q16"] = {k: int(v) for k, v in by_month.items()}

    customer_counts = df["customer_id"].value_counts()
    out["Q17"] = int((customer_counts > 3).sum())

    delivered = df[df["status"] == "delivered"]
    avg_unit_delivered = delivered.groupby("product_category")["unit_price_usd"].mean().sort_index()
    out["Q18"] = {k: _round(float(v), 2) for k, v in avg_unit_delivered.items()}

    cancel_rate = (df.assign(_c=(df["status"] == "cancelled").astype(int))
                     .groupby("country")["_c"].mean()
                     .sort_index())
    out["Q19"] = {k: _round(float(v)) for k, v in cancel_rate.items()}

    net_value = df["quantity"] * df["unit_price_usd"] * (1.0 - df["discount_pct"])
    out["Q20"] = int((net_value > 1000).sum())

    return out


def main() -> int:
    with QUESTIONS_PATH.open() as f:
        questions = json.load(f)
    expected_ids = {q["id"] for q in questions["questions"]}

    result: dict = {
        "version": "0.1.0",
        "computed_at": "2026-06-10",
        "questions_version": questions["version"],
        "by_size": {},
    }

    for size in ("S", "M", "L", "XL"):
        path = SEEDS / f"{size}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        answers = compute_for(df)
        missing = expected_ids - set(answers.keys())
        assert not missing, f"missing answers for {sorted(missing)}"
        result["by_size"][size] = {"n_rows": int(len(df)), "answers": answers}
        print(f"computed ground truth for {size} ({len(df)} rows)")

    OUT_PATH.write_text(json.dumps(result, indent=2, default=str))
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
