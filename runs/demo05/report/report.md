# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 65,680 | 20,770 | $0.028952 | 139 |
| llamaindex | 0.14.22 | 386,508 | 71,211 | $0.120147 | 97 |
| langgraph | 1.2.4 | 430,247 | 71,190 | $0.133754 | 67 |
| google_adk | 2.2.0 | 432,002 | 71,329 | $0.134668 | 83 |
| langchain | 1.3.6 | 452,402 | 71,167 | $0.140038 | 70 |
| crewai | 1.14.6 | 452,610 | 71,234 | $0.142426 | 124 |

## Cumulative input tokens per turn

| turn | colmena | llamaindex | langgraph | google_adk | langchain | crewai |
|--:|--:|--:|--:|--:|--:|--:|
| 1 | 4,711 | 3,400 | 3,338 | 3,351 | 3,353 | 3,362 |
| 2 | 10,462 | 7,172 | 7,022 | 7,185 | 7,014 | 7,019 |
| 3 | 15,872 | 10,979 | 10,741 | 11,054 | 36,850 | 36,848 |
| 4 | 21,531 | 14,800 | 40,646 | 41,256 | 63,009 | 63,004 |
| 5 | 23,450 | 18,633 | 66,856 | 67,611 | 89,196 | 89,188 |
| 6 | 29,959 | 97,727 | 141,736 | 142,786 | 164,022 | 164,013 |
| 7 | 31,627 | 146,433 | 190,409 | 191,603 | 212,659 | 212,652 |
| 8 | 38,031 | 195,182 | 239,127 | 240,461 | 261,345 | 261,350 |
| 9 | 44,910 | 315,297 | 359,057 | 360,673 | 381,235 | 381,376 |
| 10 | 65,680 | 386,508 | 430,247 | 432,002 | 452,402 | 452,610 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._

## Reading this result

**Headline.** Colmena's cumulative-input curve stays comparatively flat while every competitor grows roughly linearly in conversation history. At turn 10 Colmena spends **20,770** input tokens vs a competitor median of **71,211** (**3.4x** tax that turn). Over the whole 10-turn conversation Colmena spends **65,680** input tokens vs a competitor median of **432,002** — a **6.6x** total-token multiple, and about **4.7x** on USD.

**Why.** Two built-in Colmena behaviors, zero extra code:
1. **Ephemeral `load_attachment`** — the report document is loaded for the turn that needs it and is NOT pinned into conversation history, so it is not re-sent on every subsequent turn.
2. **Always-on base64 tool-output scrubbing** — generated chart bytes (~32KB base64 each) are elided from history instead of accumulating. Competitors on their default memory retain both, which is why their curves jump at the doc turn and at every chart turn.

**LOC framing (honest).** In THIS multi-turn demo the handler LOC is comparable across frameworks — Colmena needs a per-turn `run_dag` driver plus a DAG JSON, so it is not the smallest here. LOC is reported for completeness but is NOT the headline of this demo; the node-vs-code LOC advantage is the subject of a separate demo (#4). The real Colmena "LOC win" embedded here is that matching its scrubbing + attachment management would cost the competitors EXTRA code (manual history trimming, attachment caching, base64 elision) that their default baseline does not include.

**Fairness.** Same model, same proxy, same fixed 10-turn script, same report + chart payload for all six. Competitors use their own default idiomatic memory (no hand-tuning against them). Token counts are provider-authoritative — captured at the proxy, not self-reported by the frameworks.

