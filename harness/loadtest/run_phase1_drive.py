"""Start each server, sample its process tree, run the concurrency sweep, write
per-framework results. Colmena Serve and the LangGraph server are each started
as subprocesses so the sampler can watch the whole tree.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import time

import httpx

from harness.loadtest import driver
from harness.loadtest.aggregate import compute_metrics
from harness.loadtest.sampler import ResourceSampler

COLMENA_REPO = os.environ.get("COLMENA_REPO", "/Users/danielgarcia/startti/colmena")
COLMENA_BIN = os.environ.get(
    "COLMENA_DAG_ENGINE_BIN", f"{COLMENA_REPO}/target/release/dag_engine")
LANGGRAPH_DIR = "runners/langgraph"
LANGGRAPH_PY = f"{LANGGRAPH_DIR}/.venv/bin/python"


def _wait_health(url: str, timeout_s: float = 30.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        try:
            if httpx.get(url, timeout=2.0).status_code < 500:
                return True
        except Exception:
            time.sleep(0.3)
    return False


def _idle_rss(pid: int) -> float:
    s = ResourceSampler(pid=pid, interval=0.05)
    s.start()
    time.sleep(1.0)
    s.stop()
    return s.summarize()["rss_mean_bytes"]


def _drive_server(name, proc, run_url, health_url, concurrencies, duration_s, payload):
    assert _wait_health(health_url), f"{name} did not become healthy"
    idle = _idle_rss(proc.pid)
    levels = []
    for c in concurrencies:
        sampler = ResourceSampler(pid=proc.pid, interval=0.1)
        sampler.start()
        rec = driver.run_level(run_url, payload, c, duration_s, warmup_s=2.0)
        sampler.stop()
        summ = sampler.summarize()
        rec.update(rss_mean_bytes=summ["rss_mean_bytes"],
                   rss_peak_bytes=summ["rss_peak_bytes"],
                   rss_auc_bytes_s=summ["rss_auc_bytes_s"],
                   cpu_seconds=summ["cpu_seconds"])
        levels.append(rec)
        print(f"[{name}] C={c} thr={rec['throughput_rps']:.1f} p95={rec['p95_ms']:.0f}ms "
              f"rss={summ['rss_mean_bytes']/1e6:.0f}MB err={rec['errors']}")
    return {"framework": name, "idle_rss_bytes": idle, "levels": levels,
            "metrics": compute_metrics(levels, idle)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock-base", required=True)
    ap.add_argument("--colmena-port", type=int, required=True)
    ap.add_argument("--langgraph-port", type=int, required=True)
    ap.add_argument("--concurrencies", required=True)
    ap.add_argument("--duration-s", type=float, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    concs = [int(x) for x in a.concurrencies.split(",")]
    payload = {"prompt": "How many orders are there?"}
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # --- Colmena Serve ---
    # NOTE: the llm_call base URL is NOT a graph JSON key — the engine reads it
    # from OPENAI_BASE_URL (llm_provider_factory.rs). Must set it on the env here.
    cenv = dict(os.environ)
    cenv["DATABASE_URL"] = os.environ.get("COLMENA_DATABASE_URL", "")
    cenv["OPENAI_BASE_URL"] = f"{a.mock_base}/v1"
    cenv["OPENAI_API_KEY"] = "sk-loadtest-mock"
    colmena = subprocess.Popen(
        [COLMENA_BIN, "serve", "/tmp/loadtest_minimal.rendered.json",
         "--host", "127.0.0.1", "--port", str(a.colmena_port)],
        cwd=COLMENA_REPO, env=cenv)
    try:
        res = _drive_server(
            "colmena", colmena,
            f"http://127.0.0.1:{a.colmena_port}/run",
            f"http://127.0.0.1:{a.colmena_port}/run",  # no /health on serve; health via /run 200
            concs, a.duration_s, payload)
        (out / "colmena.json").write_text(json.dumps(res, indent=2))
    finally:
        colmena.terminate()
        colmena.wait(timeout=10)

    # --- LangGraph warm server ---
    lenv = dict(os.environ)
    lenv["LOADTEST_MOCK_BASE"] = a.mock_base
    langgraph = subprocess.Popen(
        [LANGGRAPH_PY, "-m", "runner.server.app", "--port", str(a.langgraph_port)],
        cwd=LANGGRAPH_DIR, env=lenv)
    try:
        res = _drive_server(
            "langgraph", langgraph,
            f"http://127.0.0.1:{a.langgraph_port}/run",
            f"http://127.0.0.1:{a.langgraph_port}/health",
            concs, a.duration_s, payload)
        (out / "langgraph.json").write_text(json.dumps(res, indent=2))
    finally:
        langgraph.terminate()
        langgraph.wait(timeout=10)


if __name__ == "__main__":
    main()
