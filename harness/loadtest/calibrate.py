"""One-time calibration: measure real Gemini 2.5 Flash per-call latency through
the proxy and write the p50 to runs/demo13/calibration.json. The load sweep
itself never calls a real model — this only sets the mock's fixed delay so the
numbers are representative.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import time

import httpx

N = 20
PROXY = os.environ.get("PROXY_BASE_URL", "http://127.0.0.1:4000")
KEY = os.environ.get("LITELLM_PROXY_API_KEY", os.environ.get("LITELLM_MASTER_KEY", ""))
MODEL = os.environ.get("LOADTEST_MODEL", "gemini-2.5-flash")


def main() -> None:
    latencies = []
    with httpx.Client(timeout=60.0) as c:
        for i in range(N):
            t0 = time.monotonic()
            r = c.post(f"{PROXY}/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"},
                       json={"model": MODEL, "temperature": 0.0,
                             "messages": [{"role": "user", "content": "Reply with the single word OK."}]})
            r.raise_for_status()
            latencies.append((time.monotonic() - t0) * 1000.0)
    out = {
        "model": MODEL, "n": N,
        "p50_ms": round(statistics.median(latencies), 1),
        "mean_ms": round(statistics.fmean(latencies), 1),
        "min_ms": round(min(latencies), 1), "max_ms": round(max(latencies), 1),
    }
    path = pathlib.Path("runs/demo13/calibration.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
