# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 42,847 | 2,397 | $0.018462 | 53 |

## Cumulative input tokens per turn

| turn | colmena |
|--:|--:|
| 1 | 4,901 |
| 2 | 10,838 |
| 3 | 14,318 |
| 4 | 20,685 |
| 5 | 22,596 |
| 6 | 26,620 |
| 7 | 28,660 |
| 8 | 35,621 |
| 9 | 40,450 |
| 10 | 42,847 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._


