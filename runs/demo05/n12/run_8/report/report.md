# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 33,532 | 1,823 | $0.018212 | 53 |
| langgraph | 1.2.4 | 430,222 | 71,179 | $0.133682 | 67 |
| langchain | 1.3.6 | 451,658 | 71,085 | $0.140700 | 70 |
| crewai | 1.14.6 | 452,182 | 71,192 | $0.141742 | 124 |
| llamaindex | 0.14.22 | 453,120 | 71,190 | $0.140743 | 97 |
| google_adk | 2.2.0 | 454,825 | 71,418 | $0.142185 | 83 |

## Cumulative input tokens per turn

| turn | colmena | langgraph | langchain | crewai | llamaindex | google_adk |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 4,711 | 3,338 | 3,353 | 3,362 | 3,400 | 3,351 |
| 2 | 6,157 | 7,022 | 6,997 | 6,987 | 7,152 | 7,191 |
| 3 | 7,711 | 10,741 | 36,758 | 36,752 | 37,120 | 37,382 |
| 4 | 14,392 | 40,646 | 62,859 | 62,876 | 63,320 | 63,729 |
| 5 | 16,485 | 66,862 | 88,988 | 89,028 | 89,548 | 90,104 |
| 6 | 18,644 | 141,748 | 163,680 | 163,789 | 164,498 | 165,308 |
| 7 | 21,748 | 190,420 | 212,241 | 212,396 | 213,156 | 214,141 |
| 8 | 27,918 | 239,137 | 260,846 | 261,050 | 261,863 | 263,020 |
| 9 | 31,709 | 359,043 | 380,573 | 380,990 | 381,930 | 383,407 |
| 10 | 33,532 | 430,222 | 451,658 | 452,182 | 453,120 | 454,825 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._

## Reading this result

**Headline.** Colmena's cumulative-input curve stays comparatively flat while every competitor grows roughly linearly in conversation history. At turn 10 Colmena spends **1,823** input tokens vs a competitor median of **71,190** (**39.1x** tax that turn). Over the whole 10-turn conversation Colmena spends **33,532** input tokens vs a competitor median of **452,182** — a **13.5x** total-token multiple, and about **7.7x** on USD.

**Why.** Two built-in Colmena behaviors, zero extra code:
1. **Ephemeral `load_attachment`** — the report document (~3,000 tokens) is loaded for the turn that needs it and is NOT pinned into conversation history, so it is not re-sent on every subsequent turn.
2. **Always-on base64 tool-output scrubbing** — each generated chart is ~32KB base64 ≈ **8,000 tokens**; on default memory these accumulate, so by turn 10 a competitor re-sends ~24,000 tokens of useless image bytes every call. Colmena elides them at the tool boundary. This is the dominant lever in the gap (3 charts re-sent every later turn), larger than the pinned-doc effect. Competitors' curves jump at the doc turn and step up at each chart turn.

**Anticipated objection ("you forced competitors to hoard base64 they'd never keep").** No — that IS the default. None of the 5 frameworks scrub binary/oversize tool results out of the box; retaining the tool message is standard memory behavior. Matching Colmena requires hand-written elision (detect `data:…;base64,`/oversize, replace with a marker, re-thread history). The synthetic chart (~32KB) is representative of a real chart PNG (20–100KB), not a worst case.

**LOC framing (node vs code).** The agent itself is a declarative DAG (`runners/colmena/dags/demo05_turn.json`, ~71 lines of JSON config — no loops, no conditionals, not counted as code). The Python that drives it is a THIN runner: load the DAG once, then feed each turn's message via `inject_payload`. Counting only the imperative code a developer writes and maintains, Colmena's handler is the leanest here (53 LOC) vs 67–124 for the competitors, which express the agent in imperative Python. (If you instead count the 71-line DAG as the agent definition, it is comparable to a competitor's agent code — the honest point is that the code you maintain is smaller AND you get scrubbing + attachment management for free, which competitors would need extra code to match.) The node-vs-code gap widens with agent complexity — a production agent (HITL + retries + critic + masking) stays declarative JSON in Colmena while competitor glue grows into the hundreds of lines (Demo #4).

**Fairness.** Same model, same proxy, same fixed 10-turn script, same report + chart payload for all six. Competitors use their own default idiomatic memory (no hand-tuning against them). Token counts are provider-authoritative — captured at the proxy, not self-reported by the frameworks.

