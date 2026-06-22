# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 42,444 | 2,362 | $0.017756 | 53 |

## Cumulative input tokens per turn

| turn | colmena |
|--:|--:|
| 1 | 4,901 |
| 2 | 10,746 |
| 3 | 14,223 |
| 4 | 20,502 |
| 5 | 22,377 |
| 6 | 26,417 |
| 7 | 28,436 |
| 8 | 35,349 |
| 9 | 40,082 |
| 10 | 42,444 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._


