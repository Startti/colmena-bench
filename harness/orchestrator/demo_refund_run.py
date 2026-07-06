"""Demo #4 driver — refund agent across all 6 frameworks (the integration capstone).

For each framework the production refund agent (HITL + critic-retry + masking) is
run in TWO separate processes:

  PHASE 1 — run to the human-approval suspend; the handler persists ``<output>.state``
            and returns with ``extras.suspended = True`` (no decision yet).
  PHASE 2 — a FRESH process resumes with ``--resume-state <output>.state
            --resume-answer <CANONICAL_HUMAN_ANSWER>`` and emits the final decision.

Both phases run through the live LiteLLM proxy. The proxy, started with
``BENCH_MASK_AUDIT_SECRET=<secret>``, scans every LLM request in memory and writes
``proxy/spans/mask-<run_id>.json`` = ``{"secret_leaked": bool}`` — that is the
masking audit this driver reads back.

Resume-answer format: all three competitors call ``classify_intent`` on the raw
human text, and the Colmena handler wraps a plain string into the
``A[approve_refund]: <text>`` form itself — so we pass the raw
``scenario_refund.CANONICAL_HUMAN_ANSWER`` to all four.

Scoring: ``scenario_refund.evaluate(answer, retries, secret_leaked)`` →
``{hitl_ok, critic_ok, retries, masking_ok, all_ok}``.

LOC is reported in TWO columns (the node-vs-code metric):
  * ``code_loc``   — imperative Python the developer writes/maintains
                     (``runners/<fw>/runner/tasks/task06_refund.py``).
  * ``config_loc`` — declarative config (Colmena's DAG JSON; competitors have none).

Outputs ``runs/demo06/summary.json`` and ``summary.csv`` and prints one line per
framework. Drive it via ``scripts/run_demo06.sh`` (which owns the proxy lifecycle).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR / "orchestrator"))
sys.path.insert(0, str(HARNESS_DIR))
# bench_common lives in the shared runner dir; import scenario assets for scoring.
sys.path.insert(0, str(REPO_ROOT / "runners" / "_bench_common"))

from demo05_loc import count_loc  # noqa: E402
from orchestrator.full_run import venv_python, _proxy_key  # noqa: E402
from bench_common import scenario_refund  # noqa: E402

FRAMEWORKS = ["colmena", "crewai", "langchain", "llamaindex", "langgraph", "google_adk", "pydantic_ai"]
MASK_SECRET = scenario_refund.SECRET

# Frameworks whose LLM adapter can forward the ``x-bench-run-id`` header, so the
# proxy routes their masking audit to ``mask-<run_id>.json``. Colmena's OpenAI
# adapter sends only Authorization + Content-Type (see runners/colmena/runner/
# llm.py), so its audit lands in the proxy's session file (``mask-<session_id>``)
# instead — same correlation strategy as demo05's HEADER_CAPABLE set.
HEADER_CAPABLE = {"crewai", "langchain", "langgraph", "llamaindex", "google_adk", "pydantic_ai"}

# Imperative code the developer writes/maintains (the node-vs-code "code" column).
CODE_LOC_TARGETS: dict[str, list[str]] = {
    "colmena": ["runners/colmena/runner/tasks/task06_refund.py"],
    "crewai": ["runners/crewai/runner/tasks/task06_refund.py"],
    "langchain": ["runners/langchain/runner/tasks/task06_refund.py"],
    "llamaindex": ["runners/llamaindex/runner/tasks/task06_refund.py"],
    "langgraph": ["runners/langgraph/runner/tasks/task06_refund.py"],
    "google_adk": ["runners/google_adk/runner/tasks/task06_refund.py"],
}

# Declarative config (the "config" column). Only Colmena expresses the agent as a
# DAG; competitors have no config file (the agent is all imperative code).
CONFIG_LOC_TARGETS: dict[str, list[str]] = {
    "colmena": ["runners/colmena/runner/dags/refund_agent.json"],
    "crewai": [],
    "langchain": [],
    "llamaindex": [],
    "langgraph": [],
    "google_adk": [],
}


def read_mask_audit(spans_dir: Path, run_id: str) -> bool | None:
    """Read ``mask-<run_id>.json`` written by the proxy callback.

    Returns the ``secret_leaked`` bool, or ``None`` if the audit file is absent
    (proxy not running with BENCH_MASK_AUDIT_SECRET, or no LLM call was made).
    """
    path = Path(spans_dir) / f"mask-{run_id}.json"
    if not path.exists():
        return None
    try:
        return bool(json.loads(path.read_text()).get("secret_leaked", False))
    except Exception:  # noqa: BLE001
        return None


def _loc(targets: list[str]) -> int:
    return sum(count_loc(REPO_ROOT / f) for f in targets if (REPO_ROOT / f).exists())


def _env_for(fw: str, run_id: str, proxy_base_url: str) -> dict[str, str]:
    """Subprocess env. Inherits os.environ (sourced .env carries
    COLMENA_DATABASE_URL + SECURE_VALUES_KEY for the Colmena engine), plus the
    proxy key, the masking-audit secret, and the per-run id."""
    env = os.environ.copy()
    env.update({
        "BENCH_RUN_ID": run_id,
        "LITELLM_PROXY_BASE_URL": proxy_base_url,
        "LITELLM_PROXY_API_KEY": _proxy_key(),
        "BENCH_MASK_AUDIT_SECRET": MASK_SECRET,
        "PYTHONPATH": f"{REPO_ROOT/'runners'/fw}:{REPO_ROOT/'runners'/'_bench_common'}",
    })
    return env


def _invoke(fw: str, task_path: Path, model_alias: str, proxy_base_url: str,
            run_id: str, out_path: Path, timeout: int,
            resume_state: Path | None = None,
            resume_answer: str | None = None) -> subprocess.CompletedProcess:
    py = venv_python(fw)
    cmd = [
        str(py), "-m", "runner", "--task", str(task_path), "--variant", "default",
        "--run-id", run_id, "--model-alias", model_alias,
        "--proxy-base-url", proxy_base_url, "--output", str(out_path),
        "--timeout-seconds", str(timeout),
    ]
    if resume_state is not None:
        cmd += ["--resume-state", str(resume_state)]
    if resume_answer is not None:
        cmd += ["--resume-answer", resume_answer]
    return subprocess.run(
        cmd, env=_env_for(fw, run_id, proxy_base_url),
        capture_output=True, text=True, timeout=timeout + 60,
    )


def _audit_run_id(fw: str, run_id: str, session_id: str) -> str:
    """The run id the proxy keyed the masking audit under. Header-capable runners
    forward x-bench-run-id (so it's `run_id`); colmena can't, so its audit lands
    in the proxy's session file (`session_id`)."""
    return run_id if fw in HEADER_CAPABLE else session_id


def _run_framework(fw: str, task_path: Path, model_alias: str, proxy_base_url: str,
                   out_dir: Path, spans_dir: Path, timeout: int,
                   session_id: str) -> dict[str, Any]:
    """Two-process run of one framework; returns its summary row."""
    py = venv_python(fw)
    if not py.exists():
        return {"framework": fw, "ok": False, "error": "no venv", "all_ok": False}

    run_id = f"refund-{fw}"
    fw_out = out_dir / fw
    fw_out.mkdir(parents=True, exist_ok=True)
    p1_out = fw_out / "phase1.json"
    p2_out = fw_out / "phase2.json"
    state_path = Path(str(p1_out) + ".state")

    row: dict[str, Any] = {
        "framework": fw,
        "code_loc": _loc(CODE_LOC_TARGETS.get(fw, [])),
        "config_loc": _loc(CONFIG_LOC_TARGETS.get(fw, [])),
    }

    # ---- PHASE 1: run to suspend (separate process) -------------------------
    p1 = _invoke(fw, task_path, model_alias, proxy_base_url, run_id, p1_out, timeout)
    if p1.returncode != 0:
        p1_out.with_suffix(".stderr").write_text(p1.stderr)
        return {**row, "ok": False, "error": f"phase1 exit {p1.returncode}",
                "stderr_tail": p1.stderr[-800:], "all_ok": False}
    p1_data = json.loads(p1_out.read_text()) if p1_out.exists() else {}
    p1_extras = p1_data.get("extras") or {}
    if not p1_extras.get("suspended"):
        return {**row, "ok": False,
                "error": f"phase1 did not suspend (extras={p1_extras}; "
                         f"runner_error={p1_data.get('error')})",
                "all_ok": False}
    if not state_path.exists():
        return {**row, "ok": False, "error": "phase1 wrote no .state file",
                "all_ok": False}

    # ---- PHASE 2: resume in a FRESH process ---------------------------------
    p2 = _invoke(fw, task_path, model_alias, proxy_base_url, run_id, p2_out, timeout,
                 resume_state=state_path, resume_answer=scenario_refund.CANONICAL_HUMAN_ANSWER)
    if p2.returncode != 0:
        p2_out.with_suffix(".stderr").write_text(p2.stderr)
        return {**row, "ok": False, "error": f"phase2 exit {p2.returncode}",
                "stderr_tail": p2.stderr[-800:], "all_ok": False}
    p2_data = json.loads(p2_out.read_text()) if p2_out.exists() else {}
    answer = p2_data.get("answer")
    p2_extras = p2_data.get("extras") or {}
    retries = int(p2_extras.get("retries", 0) or 0)
    runner_error = p2_data.get("error")

    # ---- masking audit + scoring -------------------------------------------
    secret_leaked = read_mask_audit(spans_dir, _audit_run_id(fw, run_id, session_id))
    # If the audit file is missing treat as not-leaked-but-unverified (None);
    # evaluate needs a bool, so coerce None -> False for the gate but keep the
    # raw value in the row for transparency.
    leaked_for_eval = bool(secret_leaked) if secret_leaked is not None else False
    checks = scenario_refund.evaluate(answer if isinstance(answer, dict) else {},
                                      retries, leaked_for_eval)

    row.update({
        "ok": runner_error is None,
        "error": runner_error,
        "answer": answer,
        "retries": retries,
        "secret_leaked": secret_leaked,
        "router_branch": p2_extras.get("router_branch"),
        "final_intent": p2_extras.get("final_intent"),
        "hitl_ok": checks["hitl_ok"],
        "critic_ok": checks["critic_ok"],
        "masking_ok": checks["masking_ok"],
        "all_ok": bool(checks["all_ok"] and runner_error is None),
    })
    return row


def _write_outputs(rows: list[dict[str, Any]], runs_dir: Path) -> tuple[Path, Path]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_path = runs_dir / "summary.json"
    csv_path = runs_dir / "summary.csv"
    json_path.write_text(json.dumps(rows, indent=2, default=str))

    cols = ["framework", "code_loc", "config_loc", "retries", "secret_leaked",
            "hitl_ok", "critic_ok", "masking_ok", "all_ok", "router_branch",
            "final_intent", "error"]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})
    return json_path, csv_path


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print("\n=== Demo #4 — refund agent summary ===")
    hdr = (f"{'framework':<12} {'code':>5} {'config':>6} {'retries':>7} "
           f"{'leaked':>6} {'all_ok':>6}  decision")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ans = r.get("answer")
        decision = ans.get("decision") if isinstance(ans, dict) else None
        leaked = r.get("secret_leaked")
        leaked_s = "?" if leaked is None else ("YES" if leaked else "no")
        line = (f"{r['framework']:<12} {r.get('code_loc',0):>5} "
                f"{r.get('config_loc',0):>6} {r.get('retries','-'):>7} "
                f"{leaked_s:>6} {str(r.get('all_ok')):>6}  {decision}")
        print(line)
        if r.get("error") or not r.get("all_ok"):
            why = r.get("error") or (
                f"hitl={r.get('hitl_ok')} critic={r.get('critic_ok')} "
                f"masking={r.get('masking_ok')}")
            print(f"             ^ NOT PASS: {why}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Demo #4 — refund agent driver")
    p.add_argument("--task", type=Path, default=REPO_ROOT / "harness/tasks/06_refund.yaml")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "runs" / "demo06" / "raw")
    p.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy" / "spans")
    p.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs" / "demo06")
    p.add_argument("--frameworks", nargs="*", default=FRAMEWORKS)
    # Must match the proxy's BENCH_RUN_ID (set by scripts/run_demo06.sh) so the
    # header-less colmena masking audit (mask-<session-id>.json) is found.
    p.add_argument("--session-id", default=os.environ.get("BENCH_RUN_ID", "demo06"))
    args = p.parse_args(argv)

    import yaml
    task_def = yaml.safe_load(args.task.read_text())
    timeout = int(task_def.get("timeout_seconds", 180))

    rows: list[dict[str, Any]] = []
    for fw in args.frameworks:
        print(f"==> {fw}")
        # Clear a stale mask audit so a leak from a prior run can't bleed in
        # (the callback is sticky-True across the two phases of THIS run). For
        # header-less colmena the audit shares the session file, so clear that too.
        run_id = f"refund-{fw}"
        for audit_id in {run_id, _audit_run_id(fw, run_id, args.session_id)}:
            stale = Path(args.spans_dir) / f"mask-{audit_id}.json"
            if stale.exists():
                stale.unlink()
        row = _run_framework(fw, args.task, args.model_alias, args.proxy_base_url,
                             args.out_dir, args.spans_dir, timeout, args.session_id)
        rows.append(row)

    json_path, csv_path = _write_outputs(rows, args.runs_dir)
    _print_summary(rows)
    print(f"\nwrote {json_path}")
    print(f"wrote {csv_path}")
    return 0 if all(r.get("all_ok") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
