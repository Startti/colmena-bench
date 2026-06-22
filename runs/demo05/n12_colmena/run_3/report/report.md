# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 37,451 | 2,303 | $0.016635 | 53 |

## Cumulative input tokens per turn

| turn | colmena |
|--:|--:|
| 1 | 4,901 |
| 2 | 6,448 |
| 3 | 9,722 |
| 4 | 11,433 |
| 5 | 13,177 |
| 6 | 19,516 |
| 7 | 23,807 |
| 8 | 30,590 |
| 9 | 35,148 |
| 10 | 37,451 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._


