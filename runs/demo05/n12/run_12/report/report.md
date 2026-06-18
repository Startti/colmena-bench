# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 37,790 | 1,949 | $0.019362 | 53 |
| langgraph | 1.2.4 | 385,351 | 71,160 | $0.119408 | 67 |
| google_adk | 2.2.0 | 432,375 | 71,432 | $0.134515 | 83 |
| langchain | 1.3.6 | 452,606 | 71,199 | $0.140817 | 70 |
| crewai | 1.14.6 | 452,832 | 71,249 | $0.142192 | 124 |
| llamaindex | 0.14.22 | 453,795 | 71,270 | $0.141206 | 97 |

## Cumulative input tokens per turn

| turn | colmena | langgraph | google_adk | langchain | crewai | llamaindex |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 4,711 | 3,338 | 3,351 | 3,353 | 3,362 | 3,400 |
| 2 | 6,062 | 7,066 | 7,185 | 7,014 | 7,019 | 7,152 |
| 3 | 7,521 | 10,829 | 11,054 | 36,857 | 36,854 | 37,170 |
| 4 | 14,237 | 14,606 | 41,256 | 63,023 | 63,021 | 63,426 |
| 5 | 15,991 | 18,395 | 67,616 | 89,217 | 89,216 | 89,710 |
| 6 | 19,352 | 96,994 | 142,807 | 164,085 | 164,118 | 164,814 |
| 7 | 25,424 | 145,631 | 191,637 | 212,757 | 212,812 | 213,559 |
| 8 | 31,823 | 194,320 | 240,529 | 261,474 | 261,555 | 262,355 |
| 9 | 35,841 | 314,191 | 360,943 | 381,407 | 381,583 | 382,525 |
| 10 | 37,790 | 385,351 | 432,375 | 452,606 | 452,832 | 453,795 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._

## Reading this result

**Headline.** Colmena's cumulative-input curve stays comparatively flat while every competitor grows roughly linearly in conversation history. At turn 10 Colmena spends **1,949** input tokens vs a competitor median of **71,249** (**36.6x** tax that turn). Over the whole 10-turn conversation Colmena spends **37,790** input tokens vs a competitor median of **452,606** — a **12.0x** total-token multiple, and about **7.3x** on USD.

**Why.** Two built-in Colmena behaviors, zero extra code:
1. **Ephemeral `load_attachment`** — the report document (~3,000 tokens) is loaded for the turn that needs it and is NOT pinned into conversation history, so it is not re-sent on every subsequent turn.
2. **Always-on base64 tool-output scrubbing** — each generated chart is ~32KB base64 ≈ **8,000 tokens**; on default memory these accumulate, so by turn 10 a competitor re-sends ~24,000 tokens of useless image bytes every call. Colmena elides them at the tool boundary. This is the dominant lever in the gap (3 charts re-sent every later turn), larger than the pinned-doc effect. Competitors' curves jump at the doc turn and step up at each chart turn.

**Anticipated objection ("you forced competitors to hoard base64 they'd never keep").** No — that IS the default. None of the 5 frameworks scrub binary/oversize tool results out of the box; retaining the tool message is standard memory behavior. Matching Colmena requires hand-written elision (detect `data:…;base64,`/oversize, replace with a marker, re-thread history). The synthetic chart (~32KB) is representative of a real chart PNG (20–100KB), not a worst case.

**LOC framing (node vs code).** The agent itself is a declarative DAG (`runners/colmena/dags/demo05_turn.json`, ~71 lines of JSON config — no loops, no conditionals, not counted as code). The Python that drives it is a THIN runner: load the DAG once, then feed each turn's message via `inject_payload`. Counting only the imperative code a developer writes and maintains, Colmena's handler is the leanest here (53 LOC) vs 67–124 for the competitors, which express the agent in imperative Python. (If you instead count the 71-line DAG as the agent definition, it is comparable to a competitor's agent code — the honest point is that the code you maintain is smaller AND you get scrubbing + attachment management for free, which competitors would need extra code to match.) The node-vs-code gap widens with agent complexity — a production agent (HITL + retries + critic + masking) stays declarative JSON in Colmena while competitor glue grows into the hundreds of lines (Demo #4).

**Fairness.** Same model, same proxy, same fixed 10-turn script, same report + chart payload for all six. Competitors use their own default idiomatic memory (no hand-tuning against them). Token counts are provider-authoritative — captured at the proxy, not self-reported by the frameworks.

