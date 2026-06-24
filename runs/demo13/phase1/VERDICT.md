# demo13 — Phase-1 verdict

**Serve concurrent?** YES (throughput C=1->ceiling x3.0; need >=3.0)

## metrics (colmena vs langgraph)

- throughput ceiling: 2.6 vs 50.4 rps - colmena loses
- min RAM/session: 0.6 vs 0.2 MB - colmena loses
- useful concurrency: 4 vs 64 - colmena loses

## Verdict: NO-GO

GO => build the other 4 servers (Phase 2). NO-GO => record the null result honestly and stop, as with demos 11/12.