# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 47,129 | 2,391 | $0.020786 | 53 |

## Cumulative input tokens per turn

| turn | colmena |
|--:|--:|
| 1 | 4,901 |
| 2 | 10,552 |
| 3 | 14,230 |
| 4 | 20,373 |
| 5 | 22,211 |
| 6 | 28,732 |
| 7 | 33,023 |
| 8 | 39,978 |
| 9 | 44,738 |
| 10 | 47,129 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._


