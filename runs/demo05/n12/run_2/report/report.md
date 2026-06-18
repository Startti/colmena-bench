# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 32,474 | 1,824 | $0.017080 | 53 |
| langgraph | 1.2.4 | 385,481 | 71,206 | $0.119044 | 67 |
| llamaindex | 0.14.22 | 386,496 | 71,211 | $0.120156 | 97 |
| google_adk | 2.2.0 | 432,211 | 71,399 | $0.134823 | 83 |
| crewai | 1.14.6 | 452,040 | 71,143 | $0.141972 | 124 |
| langchain | 1.3.6 | 452,402 | 71,167 | $0.140138 | 70 |

## Cumulative input tokens per turn

| turn | colmena | langgraph | llamaindex | google_adk | crewai | langchain |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 4,711 | 3,338 | 3,400 | 3,351 | 3,362 | 3,353 |
| 2 | 6,070 | 7,066 | 7,172 | 7,185 | 6,987 | 7,014 |
| 3 | 7,537 | 10,829 | 10,979 | 11,054 | 36,752 | 36,850 |
| 4 | 14,208 | 14,606 | 14,800 | 41,256 | 62,876 | 63,009 |
| 5 | 15,938 | 18,395 | 18,633 | 67,611 | 89,028 | 89,196 |
| 6 | 19,231 | 96,993 | 97,727 | 142,786 | 163,789 | 164,022 |
| 7 | 20,760 | 145,629 | 146,433 | 191,603 | 212,396 | 212,659 |
| 8 | 26,900 | 194,311 | 195,182 | 240,461 | 261,055 | 261,345 |
| 9 | 30,650 | 314,275 | 315,285 | 360,812 | 380,897 | 381,235 |
| 10 | 32,474 | 385,481 | 386,496 | 432,211 | 452,040 | 452,402 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._

## Reading this result

**Headline.** Colmena's cumulative-input curve stays comparatively flat while every competitor grows roughly linearly in conversation history. At turn 10 Colmena spends **1,824** input tokens vs a competitor median of **71,206** (**39.0x** tax that turn). Over the whole 10-turn conversation Colmena spends **32,474** input tokens vs a competitor median of **432,211** — a **13.3x** total-token multiple, and about **7.9x** on USD.

**Why.** Two built-in Colmena behaviors, zero extra code:
1. **Ephemeral `load_attachment`** — the report document (~3,000 tokens) is loaded for the turn that needs it and is NOT pinned into conversation history, so it is not re-sent on every subsequent turn.
2. **Always-on base64 tool-output scrubbing** — each generated chart is ~32KB base64 ≈ **8,000 tokens**; on default memory these accumulate, so by turn 10 a competitor re-sends ~24,000 tokens of useless image bytes every call. Colmena elides them at the tool boundary. This is the dominant lever in the gap (3 charts re-sent every later turn), larger than the pinned-doc effect. Competitors' curves jump at the doc turn and step up at each chart turn.

**Anticipated objection ("you forced competitors to hoard base64 they'd never keep").** No — that IS the default. None of the 5 frameworks scrub binary/oversize tool results out of the box; retaining the tool message is standard memory behavior. Matching Colmena requires hand-written elision (detect `data:…;base64,`/oversize, replace with a marker, re-thread history). The synthetic chart (~32KB) is representative of a real chart PNG (20–100KB), not a worst case.

**LOC framing (node vs code).** The agent itself is a declarative DAG (`runners/colmena/dags/demo05_turn.json`, ~71 lines of JSON config — no loops, no conditionals, not counted as code). The Python that drives it is a THIN runner: load the DAG once, then feed each turn's message via `inject_payload`. Counting only the imperative code a developer writes and maintains, Colmena's handler is the leanest here (53 LOC) vs 67–124 for the competitors, which express the agent in imperative Python. (If you instead count the 71-line DAG as the agent definition, it is comparable to a competitor's agent code — the honest point is that the code you maintain is smaller AND you get scrubbing + attachment management for free, which competitors would need extra code to match.) The node-vs-code gap widens with agent complexity — a production agent (HITL + retries + critic + masking) stays declarative JSON in Colmena while competitor glue grows into the hundreds of lines (Demo #4).

**Fairness.** Same model, same proxy, same fixed 10-turn script, same report + chart payload for all six. Competitors use their own default idiomatic memory (no hand-tuning against them). Token counts are provider-authoritative — captured at the proxy, not self-reported by the frameworks.

