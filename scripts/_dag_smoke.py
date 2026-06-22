"""Minimal Colmena run_dag smoke — drive a 1-node DAG through the proxy.

Routes Colmena's OpenAI adapter at the proxy /v1; the DAG engine needs Postgres
(COLMENA_DATABASE_URL → DATABASE_URL) and SECURE_VALUES_KEY. Usage:
    set -a; source .env; set +a
    OPENAI_BASE_URL=http://127.0.0.1:4000/v1 OPENAI_API_KEY=$LITELLM_MASTER_KEY \
    python scripts/_dag_smoke.py <dag.json>

Note: the DB is stored as COLMENA_DATABASE_URL in .env (NOT DATABASE_URL) so the
LiteLLM proxy doesn't auto-load it and crash on the missing Prisma client. The
engine reads DATABASE_URL, so this re-exports it from the proxy-safe alias.
"""
import os
import sys

if not os.environ.get("DATABASE_URL") and os.environ.get("COLMENA_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["COLMENA_DATABASE_URL"]

import colmena

dag = sys.argv[1] if len(sys.argv) > 1 else "runners/colmena/dags/smoke_hello.json"
print(f"[dag_smoke] running {dag} ...", flush=True)
res = colmena.run_dag(dag, None, None, None, True, None)
print("[dag_smoke] RESULT (first 800 chars):", flush=True)
print(res[:800] if isinstance(res, str) else res, flush=True)
