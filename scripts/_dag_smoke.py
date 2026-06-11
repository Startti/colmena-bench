"""Minimal Colmena run_dag smoke — drive a 1-node DAG through the proxy.

Routes Colmena's OpenAI adapter at the proxy /v1; the DAG engine needs
DATABASE_URL (Postgres). Usage:
    DATABASE_URL=... OPENAI_BASE_URL=http://127.0.0.1:4000/v1 \
    OPENAI_API_KEY=<proxy master key> python scripts/_dag_smoke.py <dag.json>
"""
import sys
import colmena

dag = sys.argv[1] if len(sys.argv) > 1 else "runners/colmena/dags/smoke_hello.json"
print(f"[dag_smoke] running {dag} ...", flush=True)
res = colmena.run_dag(dag, None, None, None, True, None)
print("[dag_smoke] RESULT (first 800 chars):", flush=True)
print(res[:800] if isinstance(res, str) else res, flush=True)
