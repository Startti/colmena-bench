# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 31,692 | 1,828 | $0.015158 | 53 |
| langgraph | 1.2.4 | 430,352 | 71,198 | $0.134673 | 67 |
| crewai | 1.14.6 | 452,372 | 71,223 | $0.141872 | 124 |
| langchain | 1.3.6 | 452,428 | 71,170 | $0.139966 | 70 |
| llamaindex | 0.14.22 | 453,375 | 71,221 | $0.141157 | 97 |
| google_adk | 2.2.0 | 454,617 | 71,349 | $0.141983 | 83 |

## Cumulative input tokens per turn

| turn | colmena | langgraph | crewai | langchain | llamaindex | google_adk |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 4,711 | 3,338 | 3,362 | 3,353 | 3,400 | 3,351 |
| 2 | 6,059 | 7,022 | 6,987 | 7,014 | 7,152 | 7,191 |
| 3 | 8,715 | 10,741 | 36,752 | 36,850 | 37,120 | 37,382 |
| 4 | 14,153 | 40,646 | 62,881 | 63,009 | 63,320 | 63,729 |
| 5 | 15,524 | 66,851 | 89,038 | 89,196 | 89,548 | 90,104 |
| 6 | 18,419 | 141,775 | 163,841 | 164,025 | 164,603 | 165,308 |
| 7 | 19,941 | 190,464 | 212,474 | 212,665 | 213,288 | 214,141 |
| 8 | 26,067 | 239,198 | 261,155 | 261,358 | 262,026 | 263,019 |
| 9 | 29,864 | 359,154 | 381,149 | 381,258 | 382,154 | 383,268 |
| 10 | 31,692 | 430,352 | 452,372 | 452,428 | 453,375 | 454,617 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._

## Reading this result

**Headline.** Colmena's cumulative-input curve stays comparatively flat while every competitor grows roughly linearly in conversation history. At turn 10 Colmena spends **1,828** input tokens vs a competitor median of **71,221** (**39.0x** tax that turn). Over the whole 10-turn conversation Colmena spends **31,692** input tokens vs a competitor median of **452,428** — a **14.3x** total-token multiple, and about **9.3x** on USD.

**Why.** Two built-in Colmena behaviors, zero extra code:
1. **Ephemeral `load_attachment`** — the report document (~3,000 tokens) is loaded for the turn that needs it and is NOT pinned into conversation history, so it is not re-sent on every subsequent turn.
2. **Always-on base64 tool-output scrubbing** — each generated chart is ~32KB base64 ≈ **8,000 tokens**; on default memory these accumulate, so by turn 10 a competitor re-sends ~24,000 tokens of useless image bytes every call. Colmena elides them at the tool boundary. This is the dominant lever in the gap (3 charts re-sent every later turn), larger than the pinned-doc effect. Competitors' curves jump at the doc turn and step up at each chart turn.

**Anticipated objection ("you forced competitors to hoard base64 they'd never keep").** No — that IS the default. None of the 5 frameworks scrub binary/oversize tool results out of the box; retaining the tool message is standard memory behavior. Matching Colmena requires hand-written elision (detect `data:…;base64,`/oversize, replace with a marker, re-thread history). The synthetic chart (~32KB) is representative of a real chart PNG (20–100KB), not a worst case.

**LOC framing (node vs code).** The agent itself is a declarative DAG (`runners/colmena/dags/demo05_turn.json`, ~71 lines of JSON config — no loops, no conditionals, not counted as code). The Python that drives it is a THIN runner: load the DAG once, then feed each turn's message via `inject_payload`. Counting only the imperative code a developer writes and maintains, Colmena's handler is the leanest here (53 LOC) vs 67–124 for the competitors, which express the agent in imperative Python. (If you instead count the 71-line DAG as the agent definition, it is comparable to a competitor's agent code — the honest point is that the code you maintain is smaller AND you get scrubbing + attachment management for free, which competitors would need extra code to match.) The node-vs-code gap widens with agent complexity — a production agent (HITL + retries + critic + masking) stays declarative JSON in Colmena while competitor glue grows into the hundreds of lines (Demo #4).

**Fairness.** Same model, same proxy, same fixed 10-turn script, same report + chart payload for all six. Competitors use their own default idiomatic memory (no hand-tuning against them). Token counts are provider-authoritative — captured at the proxy, not self-reported by the frameworks.

