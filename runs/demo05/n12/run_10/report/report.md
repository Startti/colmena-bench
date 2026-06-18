# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 36,661 | 1,891 | $0.016068 | 53 |
| langgraph | 1.2.4 | 385,481 | 71,206 | $0.119044 | 67 |
| langchain | 1.3.6 | 452,382 | 71,160 | $0.140067 | 70 |
| crewai | 1.14.6 | 452,753 | 71,238 | $0.142256 | 124 |
| llamaindex | 0.14.22 | 453,127 | 71,188 | $0.140921 | 97 |
| google_adk | 2.2.0 | 454,825 | 71,418 | $0.142217 | 83 |

## Cumulative input tokens per turn

| turn | colmena | langgraph | langchain | crewai | llamaindex | google_adk |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 4,711 | 3,338 | 3,353 | 3,362 | 3,400 | 3,351 |
| 2 | 10,314 | 7,066 | 7,014 | 7,019 | 7,152 | 7,191 |
| 3 | 12,871 | 10,829 | 36,850 | 36,854 | 37,120 | 37,382 |
| 4 | 18,477 | 14,606 | 63,009 | 63,021 | 63,320 | 63,729 |
| 5 | 19,936 | 18,395 | 89,196 | 89,216 | 89,548 | 90,104 |
| 6 | 22,999 | 96,993 | 164,022 | 164,096 | 164,498 | 165,308 |
| 7 | 24,601 | 145,629 | 212,659 | 212,779 | 213,156 | 214,141 |
| 8 | 30,871 | 194,311 | 261,342 | 261,510 | 261,860 | 263,020 |
| 9 | 34,770 | 314,275 | 381,222 | 381,515 | 381,939 | 383,407 |
| 10 | 36,661 | 385,481 | 452,382 | 452,753 | 453,127 | 454,825 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._

## Reading this result

**Headline.** Colmena's cumulative-input curve stays comparatively flat while every competitor grows roughly linearly in conversation history. At turn 10 Colmena spends **1,891** input tokens vs a competitor median of **71,206** (**37.7x** tax that turn). Over the whole 10-turn conversation Colmena spends **36,661** input tokens vs a competitor median of **452,753** — a **12.3x** total-token multiple, and about **8.8x** on USD.

**Why.** Two built-in Colmena behaviors, zero extra code:
1. **Ephemeral `load_attachment`** — the report document (~3,000 tokens) is loaded for the turn that needs it and is NOT pinned into conversation history, so it is not re-sent on every subsequent turn.
2. **Always-on base64 tool-output scrubbing** — each generated chart is ~32KB base64 ≈ **8,000 tokens**; on default memory these accumulate, so by turn 10 a competitor re-sends ~24,000 tokens of useless image bytes every call. Colmena elides them at the tool boundary. This is the dominant lever in the gap (3 charts re-sent every later turn), larger than the pinned-doc effect. Competitors' curves jump at the doc turn and step up at each chart turn.

**Anticipated objection ("you forced competitors to hoard base64 they'd never keep").** No — that IS the default. None of the 5 frameworks scrub binary/oversize tool results out of the box; retaining the tool message is standard memory behavior. Matching Colmena requires hand-written elision (detect `data:…;base64,`/oversize, replace with a marker, re-thread history). The synthetic chart (~32KB) is representative of a real chart PNG (20–100KB), not a worst case.

**LOC framing (node vs code).** The agent itself is a declarative DAG (`runners/colmena/dags/demo05_turn.json`, ~71 lines of JSON config — no loops, no conditionals, not counted as code). The Python that drives it is a THIN runner: load the DAG once, then feed each turn's message via `inject_payload`. Counting only the imperative code a developer writes and maintains, Colmena's handler is the leanest here (53 LOC) vs 67–124 for the competitors, which express the agent in imperative Python. (If you instead count the 71-line DAG as the agent definition, it is comparable to a competitor's agent code — the honest point is that the code you maintain is smaller AND you get scrubbing + attachment management for free, which competitors would need extra code to match.) The node-vs-code gap widens with agent complexity — a production agent (HITL + retries + critic + masking) stays declarative JSON in Colmena while competitor glue grows into the hundreds of lines (Demo #4).

**Fairness.** Same model, same proxy, same fixed 10-turn script, same report + chart payload for all six. Competitors use their own default idiomatic memory (no hand-tuning against them). Token counts are provider-authoritative — captured at the proxy, not self-reported by the frameworks.

