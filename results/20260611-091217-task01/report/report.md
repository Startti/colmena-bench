# Task `01_hello_world` — comparative report

Model: `gemini-2.5-flash` · N=10 per framework · pricing snapshot 2026-06-10

| Framework | ver | success | p50 lat (ms) | p95 lat (ms) | tok in | tok out | USD/run | USD/1k runs |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| colmena | 0.3.0 | 100% | 761 | 1070 | 14 | 19 | $0.000052 | $0.052 |
| llamaindex | 0.14.22 | 100% | 892 | 1318 | 15 | 18 | $0.000050 | $0.050 |
| langchain | 1.3.6 | 100% | 738 | 1102 | 15 | 18 | $0.000051 | $0.051 |
| langgraph | 1.2.4 | 100% | 766 | 1269 | 15 | 18 | $0.000051 | $0.051 |
| google_adk | 2.2.0 | 100% | 1612 | 1767 | 35 | 28 | $0.000081 | $0.081 |
| crewai | 1.14.6 | 100% | 1060 | 1357 | 77 | 57 | $0.000167 | $0.167 |

_Tokens are provider-authoritative (captured at the proxy). Latency is wall-clock measured by each runner. Cost uses the dated pricing table; cached-input discount applied where the provider reports cached tokens._

