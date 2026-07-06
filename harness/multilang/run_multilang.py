#!/usr/bin/env python3
"""E-4 — the same Colmena engine, three languages.

Runs ONE deterministic DAG (``graphs/power.json``: mock_input(5) -> exponential(3)
-> log => 125) through each of Colmena's three language front doors and proves they
return the identical result. All three call the SAME Rust function
(``dag_engine::api::run_dag``); the only differences below are the language of the
caller:

  * Rust    — the ``dag_engine`` CLI binary (``dag_engine run <file>``).
  * Python  — the PyO3 binding (``colmena.run_dag``), the one every Colmena runner
              in this benchmark already uses.
  * Node/TS — the napi binding published as ``colmena-ai`` (``runDag``).

This is the evidence for the whitepaper's "polyglot engine" claim: the benchmark's
Colmena arm is not a Python-only artifact — the exact same engine is callable from
Rust, Python and TypeScript, so a team can adopt Colmena in whichever runtime their
stack uses.

Prereqs (all produced by scripts/setup_all.sh + a colmena checkout):
  * COLMENA_REPO points at the colmena checkout (default: ../colmena).
  * Rust binary built:   cargo build --release --bin dag_engine
  * Python binding:      runners/colmena/.venv (maturin develop)
  * Node binding built:  (cd $COLMENA_REPO && npm install && npm run build)
  * DATABASE_URL / COLMENA_DATABASE_URL set (the engine builds a PG registry even
    though this compute-only DAG never touches the DB).

Usage:
  runners/colmena/.venv/bin/python harness/multilang/run_multilang.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parents[1]
DEFAULT_DAG = HARNESS_DIR / "graphs" / "power.json"
RESULT_SENTINEL = "RESULT_JSON:"


def _colmena_repo() -> Path:
    return Path(os.environ.get("COLMENA_REPO", str(REPO_ROOT.parent / "colmena"))).resolve()


def _env() -> dict[str, str]:
    """Engine env: the Rust CLI + PyO3 binding read DATABASE_URL (the Python runner
    maps COLMENA_DATABASE_URL -> DATABASE_URL); mirror that here."""
    env = os.environ.copy()
    if "DATABASE_URL" not in env and "COLMENA_DATABASE_URL" in env:
        env["DATABASE_URL"] = env["COLMENA_DATABASE_URL"]
    return env


def _normalize(result: Any) -> Any:
    """Drop the per-run session id and coerce numbers to float so 125 == 125.0
    across languages (JSON emits 125 from Node, 125.0 from Rust/Python)."""
    if isinstance(result, dict):
        return {k: _normalize(v) for k, v in result.items() if k != "__colmena_session_id"}
    if isinstance(result, list):
        return [_normalize(v) for v in result]
    if isinstance(result, bool):
        return result
    if isinstance(result, (int, float)):
        return float(result)
    return result


def _run(cmd: list[str], env: dict[str, str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def run_rust(dag: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    """dag_engine CLI: parse the SSE `data: {"type":"finish",...,"output":{...}}` line."""
    binary = _colmena_repo() / "target" / "release" / "dag_engine"
    if not binary.exists():
        return {"ok": False, "error": f"binary not built: {binary}"}
    t0 = time.perf_counter()
    proc = _run([str(binary), "run", str(dag)], env, timeout)
    latency = int((time.perf_counter() - t0) * 1000)
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip()[:400] or f"exit {proc.returncode}"}
    output = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[len("data:"):].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(evt, dict) and evt.get("type") == "finish":
            output = evt.get("output")
    if output is None:
        return {"ok": False, "error": "no finish event in output"}
    return {"ok": True, "result": output, "latency_ms": latency}


def run_python(dag: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    """PyO3 binding: colmena.run_dag returns a JSON string."""
    py = REPO_ROOT / "runners" / "colmena" / ".venv" / "bin" / "python"
    if not py.exists():
        return {"ok": False, "error": f"venv not built: {py}"}
    code = (
        "import colmena, json\n"
        f"res = colmena.run_dag({str(dag)!r})\n"
        "res = json.loads(res) if isinstance(res, str) else res\n"
        # compact to a single line so the sentinel parse gets the whole object
        f"print({RESULT_SENTINEL!r} + json.dumps(res, default=str))\n"
    )
    env2 = {**env, "VIRTUAL_ENV": str(py.parent.parent)}
    t0 = time.perf_counter()
    proc = _run([str(py), "-c", code], env2, timeout)
    latency = int((time.perf_counter() - t0) * 1000)
    return _parse_sentinel(proc, latency)


def run_node(dag: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    """napi binding (colmena-ai): runDag returns an object."""
    facade = _colmena_repo() / "lib" / "index.js"
    if not facade.exists():
        return {"ok": False, "error": f"node binding not built: {facade} (npm run build)"}
    code = (
        f"const c = require({str(facade)!r});\n"
        f"c.runDag({str(dag)!r}).then(r => console.log({RESULT_SENTINEL!r} + JSON.stringify(r)))"
        ".catch(e => { console.error(e.message); process.exit(1); });"
    )
    t0 = time.perf_counter()
    proc = _run(["node", "-e", code], env, timeout)
    latency = int((time.perf_counter() - t0) * 1000)
    return _parse_sentinel(proc, latency)


def _parse_sentinel(proc: subprocess.CompletedProcess, latency: int) -> dict[str, Any]:
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip()[:400] or f"exit {proc.returncode}"}
    for line in proc.stdout.splitlines():
        if line.startswith(RESULT_SENTINEL):
            return {"ok": True, "result": json.loads(line[len(RESULT_SENTINEL):]), "latency_ms": latency}
    return {"ok": False, "error": "no RESULT_JSON line in output"}


SDKS = {
    "rust": ("dag_engine run <file> (CLI binary)", run_rust),
    "python": ("colmena.run_dag (PyO3 binding)", run_python),
    "node": ("colmena-ai runDag (napi binding)", run_node),
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="E-4 — same Colmena engine, three languages")
    p.add_argument("--dag", type=Path, default=DEFAULT_DAG)
    p.add_argument("--out", type=Path, default=REPO_ROOT / "runs" / "demo_multilang" / "summary.json")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--sdks", nargs="*", default=list(SDKS), choices=list(SDKS))
    args = p.parse_args(argv)

    env = _env()
    rows: dict[str, Any] = {}
    for name in args.sdks:
        label, fn = SDKS[name]
        print(f"==> {name:7} ({label})")
        res = fn(args.dag, env, args.timeout)
        res["entrypoint"] = label
        res["normalized"] = _normalize(res["result"]) if res.get("ok") else None
        rows[name] = res
        if res.get("ok"):
            print(f"    result: {json.dumps(res['normalized'])}  ({res['latency_ms']} ms)")
        else:
            print(f"    ERROR: {res['error']}")

    oks = [n for n in args.sdks if rows[n].get("ok")]
    normalized = [rows[n]["normalized"] for n in oks]
    identical = len(normalized) >= 2 and all(x == normalized[0] for x in normalized)

    summary = {
        "dag": str(args.dag.relative_to(REPO_ROOT)) if args.dag.is_relative_to(REPO_ROOT) else str(args.dag),
        "engine_fn": "dag_engine::api::run_dag (identical Rust core for all three)",
        "sdks_run": args.sdks,
        "sdks_ok": oks,
        "identical_output": identical,
        "shared_result": normalized[0] if identical else None,
        "per_sdk": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, default=str))

    print("\n=== E-4 — same engine, three languages ===")
    print(f"{'sdk':8} {'ok':4} {'latency_ms':>10}  result")
    print("-" * 60)
    for name in args.sdks:
        r = rows[name]
        res_s = json.dumps(r["normalized"]) if r.get("ok") else r.get("error", "")[:40]
        print(f"{name:8} {'yes' if r.get('ok') else 'NO':4} {r.get('latency_ms', 0):>10}  {res_s}")
    print("-" * 60)
    print(f"identical output across {len(oks)} SDKs: {'YES ✓' if identical else 'NO ✗'}")
    print(f"wrote {args.out}")
    return 0 if identical else 1


if __name__ == "__main__":
    sys.exit(main())
