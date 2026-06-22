# Demo 05 — "The Context Tax" · Chart Gallery (N=12)

Fixed 10-turn report-assistant conversation, 6 frameworks, `gemini-2.5-flash`,
provider-authoritative tokens (proxy), mean ± std over 12 runs.

**Headline:** Colmena **37,619 ± 5,603** total input tokens vs competitors **404k–452k**
→ **~12×** fewer tokens · **~37×** at turn 10 · **~7.6×** cheaper · **RAM 49 MB** (lowest)
· **quality 0.99** (tied) · **53 LOC** maintained (agent = 71-line declarative DAG).

> Data: `agg_n12.json`, `agg_n12_summary.csv`. Reproduce: see
> [`../../../docs/demos/demo05-replication.md`](../../../docs/demos/demo05-replication.md).

---

## ★ Recommended pitch set (5 charts, in order)

A tight, non-redundant sequence — the rest below are backup/detail.

1. **`2_line_cumulative`** — *"Watch what a normal multi-turn agent costs."* The
   asymptote: Colmena flat, everyone else climbing. The single most convincing slide.
2. **`14_quadrant_cost_quality`** — *"And it's not a quality tradeoff."* Colmena alone
   in the cheap + high-quality corner (LLM-judged 0.99, tied).
3. **`4_bar_usd`** — *"In money, at scale."* USD/conversation + the $/year projection.
4. **`11_bar_ram`** — *"And it's lighter."* Rust footprint: 49 MB vs 96–279.
5. **`5_multiplier_curve`** — *"And it compounds — the longer the chat, the bigger the gap."*

Honesty slide to keep handy: CPU is mid-pack and wall-clock isn't featured (bench
artifact) — leading with these makes the strong claims land. See
[`../../../docs/SELLING_COLMENA.md`](../../../docs/SELLING_COLMENA.md).

---

## Headliners (the pitch)

### Cumulative input tokens per turn — the asymptote
Colmena stays flat; the five competitors climb with every turn.
![cumulative](plots/2_line_cumulative.png)

### Total input tokens (mean ± std)
![total tokens](plots/1_bar_total_tokens.png)

### Cost × quality — Colmena is cheap AND high-quality
Top-left wins: Colmena alone in the cheap + high-quality corner.
![cost x quality](plots/14_quadrant_cost_quality.png)

### Cost in USD + at-scale projection
![usd](plots/4_bar_usd.png)

### The advantage compounds with conversation length
![multiplier](plots/5_multiplier_curve.png)

---

## Resources

### Peak RAM — Colmena lowest (Rust)
![ram](plots/11_bar_ram.png)

### CPU seconds — honest: Colmena mid-pack
![cpu](plots/12_bar_cpu.png)

### Total provider latency
![latency](plots/9_bar_latency.png)

---

## Node vs code & quality

### Maintained imperative code (LOC) — agent itself is a declarative DAG
![loc](plots/7_loc_bar.png)

### Cost × maintained code
![quadrant cost-code](plots/6_quadrant.png)

### Answer quality (LLM-judge, 0–1) — all tied near 1.0
Colmena's token savings cost no measurable quality.
![quality](plots/13_bar_quality.png)

---

## Detail / explanatory

### Per-turn input cost
![per turn](plots/3_line_per_turn.png)

### LLM calls per turn (Colmena's extra load_attachment round-trips)
![calls](plots/10_line_calls.png)

### Where the tokens go (estimated composition)
![composition](plots/8_stacked_composition.png)
