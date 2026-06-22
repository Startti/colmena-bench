# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 24,629 | 2,067 | $0.011996 | 53 |

## Cumulative input tokens per turn

| turn | colmena |
|--:|--:|
| 1 | 4,901 |
| 2 | 6,435 |
| 3 | 9,681 |
| 4 | 11,377 |
| 5 | 13,101 |
| 6 | 16,811 |
| 7 | 18,683 |
| 8 | 20,600 |
| 9 | 22,562 |
| 10 | 24,629 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._


