# orders_synthetic

Deterministic synthetic e-commerce orders dataset used by the killer demo
(the Query-Strategy Trade-off) and several other benchmarks.

## Sizes

| Variant | Rows | File | Notes |
|---|---|---|---|
| S | 500 | `seeds/S.csv` | Fits in any context window. Sanity check. |
| M | 5,000 | `seeds/M.csv` | Naive "stuff into context" starts hurting. |
| L | 50,000 | `seeds/L.csv` | Naive implementations fail. Killer demo asymptote. |
| XL | 500,000 | `seeds/XL.csv` | Generated on demand for T25. Only frameworks with pandas/SQL paths survive. |

> CSV seeds are **gitignored** — too large to commit and trivially
> regenerable. Run `make seeds` (T19) or:
>
> ```bash
> python data/orders_synthetic/generator.py --size S --out data/orders_synthetic/seeds/S.csv
> python data/orders_synthetic/generator.py --size M --out data/orders_synthetic/seeds/M.csv
> python data/orders_synthetic/generator.py --size L --out data/orders_synthetic/seeds/L.csv
> # XL: ~30s wallclock, ~100 MB file
> python data/orders_synthetic/generator.py --size XL --out data/orders_synthetic/seeds/XL.csv
> ```

## Determinism contract

- Same `--size` + same `--seed` (default 42) ⇒ byte-identical CSV.
- **Row `i` is the same across sizes.** Larger sizes are just more rows
  appended; the first 500 rows of L equal `seeds/S.csv`.
- This invariant lets us isolate the "tokens vs rows" axis without
  changing data shape underneath the framework.

Verify by hand:

```bash
diff <(head -5 seeds/S.csv) <(head -5 seeds/L.csv)   # must be empty
```

## Columns

See `schema.json` for the JSON Schema. Quick reference:

| Column | Type | Range |
|---|---|---|
| `order_id` | string `O[0-9]{9}` | Sequential, stable across sizes |
| `customer_id` | string `C[0-9]{6}` | 50,000 distinct customers ⇒ repeat rate grows with size |
| `order_date` | date | 2024-01-01 to 2025-12-31 |
| `country` | enum 8 LATAM + US + ES | Weighted toward MX, AR, BR |
| `channel` | enum web/mobile/phone/store | 85 % web+mobile |
| `product_id` | string `P[0-9]{5}` | 5,000 distinct SKUs |
| `product_category` | enum 7 cats | Uniform |
| `quantity` | int 1-20 | Uniform |
| `unit_price_usd` | float | Category-dependent (electronics up to $2,500) |
| `discount_pct` | float | Mostly 0; long tail to 0.5 |
| `shipping_usd` | float | 0 for store channel; price-dependent otherwise |
| `status` | enum | 55 % delivered |
| `payment_method` | enum | 55 % card |

## Why this dataset

The Query-Strategy Trade-off ("CSV killer demo") asks an agent 20 analytical questions over this
table at sizes S→XL. The expected outcome:

- **Naive implementations** (the default "load CSV into context" path that
  every framework tutorial suggests) explode in tokens as `n_rows` grows
  and break entirely at L.
- **Expert implementations** (pandas / SQL tool calls) stay O(1) in tokens
  and finish at every size.

The asymptote between those two curves is the chart this benchmark exists
to publish.
