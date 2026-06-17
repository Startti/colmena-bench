# Hero Demo #1 — The Context Tax (multi-turn token asymptote)

Fixed 10-turn report-assistant conversation. Tokens are provider-authoritative (captured at the proxy). Lower is better.

| Framework | ver | total tok in | turn-10 tok in | USD (total) | handler LOC |
|---|---|--:|--:|--:|--:|
| colmena | 0.4.0 | 40,528 | 1,965 | $0.020141 | 201 |
| crewai | 1.14.6 | 452,078 | 71,137 | $0.141851 | 165 |

## Cumulative input tokens per turn

| turn | colmena | crewai |
|--:|--:|--:|
| 1 | 4,711 | 3,362 |
| 2 | 6,055 | 6,987 |
| 3 | 8,814 | 36,752 |
| 4 | 14,292 | 62,876 |
| 5 | 15,671 | 89,028 |
| 6 | 21,492 | 163,821 |
| 7 | 27,579 | 212,444 |
| 8 | 34,500 | 261,111 |
| 9 | 38,563 | 380,941 |
| 10 | 40,528 | 452,078 |

_Competitors run their **default idiomatic** multi-turn memory (full history, retained tool outputs). To match Colmena they would need to add manual history trimming, attachment caching, and base64 scrubbing — extra code Colmena provides built-in (extra LOC = 0)._

