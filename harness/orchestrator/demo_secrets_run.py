"""Demo #10 driver — secure_suspend secrets agent across all 6 frameworks.

Cloned from ``demo_refund_run.py`` (the proven two-phase / mask-keying driver).
The scenario: an onboarding agent must collect 3 fake credentials from the user
and deliver them (the REAL values) to a mock "connect account" endpoint, WITHOUT
the secrets ever reaching the LLM / proxy.

Cells = framework x variant ∈ {collect, echo} x seed.

  * ``collect`` — the only leak path is in-conversation credential collection.
  * ``echo``    — the mock echoes the secret back in its response, testing whether
                  the echoed secret re-reaches the LLM (outbound echo-masking).

Colmena should be ``secret_leaked=false`` in BOTH variants (handles in collect; a
re-masked tool-response in echo). Competitors leak (``true``) in both — they put
the credential into the prompt at collection time. Both variants are meaningful;
we record per (framework, variant, seed).

Per cell the driver:
  1. picks a unique localhost port and starts ``mock_account_api.start_mock`` with
     ``echo=(variant=='echo')``, recording the received body to
     ``runs/demo10/received-<run_id>.json``.
  2. builds the subprocess env (clone of refund's ``_env_for``) and ADDS the
     mask-audit needle (``ss.MARKER``), the mock URL/record path, and the run id.
  3. runs the cell — colmena TWO-PHASE (phase 1 -> ``.state`` -> phase 2 resume,
     exactly like the refund driver); competitors a SINGLE invocation (they never
     suspend).
  4. scores: ``secret_leaked = ss.read_leaked(mask_file)`` (mask file keyed per
     refund's run-id logic — see ``_mask_run_id``/``_mask_path`` below),
     ``delivered_to_api = ss.delivered_to_api(record_path)``, and ``round_trips``
     (colmena ``extras.round_trips``, else 1).
  5. shuts down the mock and appends a summary row.

Outputs ``runs/demo10/summary.{json,csv}``. Drive it via the Task 6 run script,
which owns the proxy lifecycle.

CRITICAL — the mask audit reads the proxy's OWN process env at call time. The
proxy callback scans every LLM request body for ``BENCH_MASK_AUDIT_SECRET`` taken
from the PROXY process environment, not from any per-request header. So the RUN
SCRIPT (Task 6) MUST export ``BENCH_MASK_AUDIT_SECRET=<ss.MARKER>`` BEFORE starting
the proxy — otherwise the audit never fires and every ``mask-*.json`` is absent
(``secret_leaked`` reads back as ``None``). This driver also sets the same value in
each subprocess env for completeness / header-capable correlation, but that does
NOT substitute for arming the proxy process itself.
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
# bench_common lives in the shared runner dir; import scenario assets + scorers.
sys.path.insert(0, str(REPO_ROOT / "runners" / "_bench_common"))

from orchestrator.full_run import venv_python, _proxy_key  # noqa: E402
from mock_account_api import start_mock  # noqa: E402
from bench_common import scenario_secrets as ss  # noqa: E402

FRAMEWORKS = ["colmena", "crewai", "langchain", "langgraph", "llamaindex", "google_adk"]
VARIANTS = ["collect", "echo"]

# Steelman arms: pseudo-framework names that reuse a real runner's venv/runner code
# but flip an env switch to select a hand-architected variant. ``_ARM_MAP`` resolves
# an arm to ``(runner_fw, extra_env)``. ``langgraph_interrupt_isolated`` drives the
# LangGraph ``interrupt()`` out-of-band-collection arm (task10_secrets._run_isolated):
# it collects the secret via the interrupt channel so it never reaches the LLM, the
# hand-wired analog of Colmena's secure_suspend. Not in the default matrix — opt in
# with ``--frameworks langgraph_interrupt_isolated``.
_ARM_MAP: dict[str, tuple[str, dict[str, str]]] = {
    "langgraph_interrupt_isolated": ("langgraph", {"BENCH_LANGGRAPH_ISOLATED": "1"}),
}

# The mask-audit needle. The PROXY must be started with this same value in its
# process env (see module docstring) for the audit to fire.
MASK_SECRET = ss.MARKER

# Frameworks whose LLM adapter forwards the ``x-bench-run-id`` header, so the proxy
# routes their masking audit to ``mask-<run_id>.json``. Colmena's OpenAI adapter
# sends only Authorization + Content-Type, so its audit lands in the proxy's
# session file (``mask-<PROXY_BENCH_RUN_ID>.json``). Same set + correlation
# strategy as demo_refund_run's HEADER_CAPABLE.
HEADER_CAPABLE = {"crewai", "langchain", "langgraph", "llamaindex", "google_adk",
                  "langgraph_interrupt_isolated"}

# Base port for the per-cell mock; cell index is added (8810, 8811, ...).
BASE_PORT = 8810


def _env_for(fw: str, run_id: str, proxy_base_url: str, port: int,
             record_path: Path) -> dict[str, str]:
    """Subprocess env (clone of demo_refund_run._env_for) PLUS the demo10 deltas.

    Inherits os.environ (sourced .env carries COLMENA_DATABASE_URL +
    SECURE_VALUES_KEY for the Colmena engine), plus the proxy key, the mask-audit
    needle, the per-run id, and the mock URL/record path the connect tool reads
    in-process via ``os.environ``.
    """
    env = os.environ.copy()
    env.update({
        "BENCH_RUN_ID": run_id,
        "LITELLM_PROXY_BASE_URL": proxy_base_url,
        "LITELLM_PROXY_API_KEY": _proxy_key(),
        # The needle the proxy audits. NOTE: this covers header-capable
        # correlation, but the PROXY PROCESS must also be started with this value
        # (the run script in Task 6 exports it before launching the proxy) — the
        # audit callback reads the proxy's own env, not this subprocess env.
        "BENCH_MASK_AUDIT_SECRET": MASK_SECRET,
        # The mock "connect account" endpoint the connect tool POSTs to, and the
        # record path it writes the received body to.
        "BENCH_MOCK_URL": f"http://127.0.0.1:{port}/connect",
        "BENCH_MOCK_RECORD": str(record_path),
        "PYTHONPATH": f"{REPO_ROOT/'runners'/fw}:{REPO_ROOT/'runners'/'_bench_common'}",
    })
    return env


def _invoke(fw: str, task_path: Path, variant: str, model_alias: str,
            proxy_base_url: str, run_id: str, out_path: Path, timeout: int,
            env: dict[str, str], resume_state: Path | None = None,
            resume_answer: str | None = None) -> subprocess.CompletedProcess:
    """Single ``python -m runner`` invocation (mirrors demo_refund_run._invoke).

    Competitors read the variant (collect/echo) to decide whether to fold the
    mock's echoed response back into the LLM; colmena ignores it but accepts it.
    """
    py = venv_python(fw)
    cmd = [
        str(py), "-m", "runner", "--task", str(task_path), "--variant", variant,
        "--run-id", run_id, "--model-alias", model_alias,
        "--proxy-base-url", proxy_base_url, "--output", str(out_path),
        "--timeout-seconds", str(timeout),
    ]
    if resume_state is not None:
        cmd += ["--resume-state", str(resume_state)]
    if resume_answer is not None:
        cmd += ["--resume-answer", resume_answer]
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout + 60,
    )


def _mask_run_id(fw: str, run_id: str, session_id: str) -> str:
    """The id the proxy keyed the masking audit under (clone of demo_refund_run's
    ``_audit_run_id``). Header-capable runners forward x-bench-run-id (so it's
    ``run_id``); colmena can't, so its audit lands in the proxy's session file
    (``session_id`` = PROXY_BENCH_RUN_ID)."""
    return run_id if fw in HEADER_CAPABLE else session_id


def _mask_path(spans_dir: Path, fw: str, run_id: str, session_id: str) -> Path:
    """``proxy/spans/mask-<id>.json`` for the right id per ``_mask_run_id``."""
    return Path(spans_dir) / f"mask-{_mask_run_id(fw, run_id, session_id)}.json"


def _read_extras(out_path: Path) -> dict[str, Any]:
    if not out_path.exists():
        return {}
    try:
        return json.loads(out_path.read_text()).get("extras") or {}
    except Exception:  # noqa: BLE001
        return {}


def _run_colmena(task_path: Path, variant: str, model_alias: str,
                 proxy_base_url: str, run_id: str, cell_out: Path, timeout: int,
                 env: dict[str, str]) -> tuple[int, str, dict[str, Any]]:
    """TWO-PHASE colmena run (clone of demo_refund_run two-phase invocation):
    phase 1 -> writes ``<output>.state`` with ``extras.suspended=True`` -> phase 2
    resumes in a FRESH process. Returns (round_trips, error, phase2_extras)."""
    p1_out = cell_out / "phase1.json"
    p2_out = cell_out / "phase2.json"
    state_path = Path(str(p1_out) + ".state")

    # ---- PHASE 1: run to the secure_suspend (separate process) --------------
    p1 = _invoke("colmena", task_path, variant, model_alias, proxy_base_url,
                 run_id, p1_out, timeout, env)
    if p1.returncode != 0:
        p1_out.with_suffix(".stderr").write_text(p1.stderr)
        return 0, f"phase1 exit {p1.returncode}: {p1.stderr[-400:]}", {}
    p1_extras = _read_extras(p1_out)
    if not p1_extras.get("suspended"):
        return 0, f"phase1 did not suspend (extras={p1_extras})", {}
    if not state_path.exists():
        return 0, "phase1 wrote no .state file", {}

    # ---- PHASE 2: resume in a FRESH process ---------------------------------
    # The colmena runner computes each pending credential's REAL value itself from
    # ss.secrets(); we still pass ss.resume_payload() as --resume-answer for
    # parity with the refund driver's contract (harmless for colmena).
    p2 = _invoke("colmena", task_path, variant, model_alias, proxy_base_url,
                 run_id, p2_out, timeout, env, resume_state=state_path,
                 resume_answer=ss.resume_payload())
    if p2.returncode != 0:
        p2_out.with_suffix(".stderr").write_text(p2.stderr)
        return 0, f"phase2 exit {p2.returncode}: {p2.stderr[-400:]}", {}
    p2_extras = _read_extras(p2_out)
    err = None
    try:
        err = json.loads(p2_out.read_text()).get("error") if p2_out.exists() else None
    except Exception:  # noqa: BLE001
        err = None
    return int(p2_extras.get("round_trips", 1) or 1), err, p2_extras


def _run_competitor(fw: str, task_path: Path, variant: str, model_alias: str,
                    proxy_base_url: str, run_id: str, cell_out: Path, timeout: int,
                    env: dict[str, str]) -> tuple[int, str]:
    """SINGLE ``python -m runner`` invocation — competitors never suspend.
    Returns (round_trips=1, error)."""
    out = cell_out / "run.json"
    p = _invoke(fw, task_path, variant, model_alias, proxy_base_url, run_id, out,
                timeout, env)
    if p.returncode != 0:
        out.with_suffix(".stderr").write_text(p.stderr)
        return 1, f"exit {p.returncode}: {p.stderr[-400:]}"
    err = None
    try:
        err = json.loads(out.read_text()).get("error") if out.exists() else None
    except Exception:  # noqa: BLE001
        err = None
    return 1, err


def _run_cell(fw: str, variant: str, seed: int, cell_index: int, task_path: Path,
              model_alias: str, proxy_base_url: str, out_dir: Path, spans_dir: Path,
              runs_dir: Path, timeout: int, session_id: str) -> dict[str, Any]:
    """One framework x variant x seed cell. Starts a mock, runs, scores, shuts
    the mock down, returns the summary row."""
    # Resolve steelman arms to their backing runner + env switch (real frameworks
    # map to themselves with no extra env).
    runner_fw, arm_env = _ARM_MAP.get(fw, (fw, {}))

    py = venv_python(runner_fw)
    if not py.exists():
        return {"framework": fw, "variant": variant, "seed": seed,
                "secret_leaked": None, "delivered_to_api": False,
                "round_trips": 0, "error": "no venv"}

    run_id = f"d10-{fw}-{variant}-s{seed}"
    port = BASE_PORT + cell_index
    record_path = runs_dir / f"received-{run_id}.json"
    if record_path.exists():
        record_path.unlink()  # don't let a prior delivery bleed in

    cell_out = out_dir / f"{fw}-{variant}-s{seed}"
    cell_out.mkdir(parents=True, exist_ok=True)

    # Clear any stale mask audit so a leak from a prior run can't bleed in (the
    # proxy callback is sticky-True within a run; for header-less colmena the audit
    # shares the session file, so clear that too).
    for stale in {
        Path(spans_dir) / f"mask-{run_id}.json",
        _mask_path(spans_dir, fw, run_id, session_id),
    }:
        if stale.exists():
            stale.unlink()

    env = _env_for(runner_fw, run_id, proxy_base_url, port, record_path)
    env.update(arm_env)  # arm-specific switch (e.g. BENCH_LANGGRAPH_ISOLATED=1)

    srv = start_mock(port, str(record_path), echo=(variant == "echo"))
    try:
        if runner_fw == "colmena":
            round_trips, error, _ = _run_colmena(
                task_path, variant, model_alias, proxy_base_url, run_id,
                cell_out, timeout, env)
        else:
            round_trips, error = _run_competitor(
                runner_fw, task_path, variant, model_alias, proxy_base_url, run_id,
                cell_out, timeout, env)

        secret_leaked = ss.read_leaked(str(_mask_path(spans_dir, fw, run_id, session_id)))
        delivered_to_api = ss.delivered_to_api(str(record_path))
    finally:
        srv.shutdown()

    return {
        "framework": fw,
        "variant": variant,
        "seed": seed,
        "secret_leaked": secret_leaked,
        "delivered_to_api": delivered_to_api,
        "round_trips": round_trips,
        "error": error,
    }


def _write_outputs(rows: list[dict[str, Any]], runs_dir: Path) -> tuple[Path, Path]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    json_path = runs_dir / "summary.json"
    csv_path = runs_dir / "summary.csv"
    json_path.write_text(json.dumps(rows, indent=2, default=str))

    cols = ["framework", "variant", "seed", "secret_leaked", "delivered_to_api",
            "round_trips", "error"]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c) for c in cols})
    return json_path, csv_path


def _merge_baseline(rows: list[dict[str, Any]], runs_dir: Path) -> list[dict[str, Any]]:
    """Merge in previously-recorded rows for frameworks/variants/seeds not in this
    run (clone of refund's --merge-baseline: re-run a subset without dropping the
    rest of the matrix). Keys on (framework, variant, seed)."""
    prior_path = runs_dir / "summary.json"
    if not prior_path.exists():
        return rows
    try:
        prior = json.loads(prior_path.read_text())
    except Exception:  # noqa: BLE001
        return rows
    have = {(r["framework"], r["variant"], r["seed"]) for r in rows}
    merged = list(rows)
    for r in prior:
        key = (r.get("framework"), r.get("variant"), r.get("seed"))
        if key not in have:
            merged.append(r)
    merged.sort(key=lambda r: (str(r.get("framework")), str(r.get("variant")),
                               r.get("seed", 0)))
    return merged


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print("\n=== Demo #10 — secure_suspend secrets summary ===")
    hdr = (f"{'framework':<12} {'variant':<8} {'seed':>4} {'leaked':>6} "
           f"{'delivered':>9} {'trips':>5}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        leaked = r.get("secret_leaked")
        leaked_s = "?" if leaked is None else ("YES" if leaked else "no")
        line = (f"{r['framework']:<12} {r.get('variant',''):<8} "
                f"{r.get('seed',''):>4} {leaked_s:>6} "
                f"{str(r.get('delivered_to_api')):>9} {r.get('round_trips',''):>5}")
        print(line)
        if r.get("error"):
            print(f"             ^ error: {r['error']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Demo #10 — secure_suspend secrets driver")
    p.add_argument("--task", type=Path,
                   default=REPO_ROOT / "harness/tasks/10_secrets.yaml")
    p.add_argument("--model-alias", default="gemini-2.5-flash")
    p.add_argument("--proxy-base-url", default="http://127.0.0.1:4000")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "runs" / "demo10" / "raw")
    p.add_argument("--spans-dir", type=Path, default=REPO_ROOT / "proxy" / "spans")
    p.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs" / "demo10")
    p.add_argument("--frameworks", nargs="*", default=FRAMEWORKS,
                   help='e.g. --frameworks "colmena crewai"')
    p.add_argument("--variants", default=",".join(VARIANTS),
                   help="comma-separated subset of collect,echo")
    p.add_argument("--seeds", type=int, default=1, help="seeds per (framework,variant)")
    p.add_argument("--merge-baseline", action="store_true",
                   help="keep prior summary rows for cells not in THIS run")
    # Must match the proxy's BENCH_RUN_ID (set by the Task 6 run script) so the
    # header-less colmena masking audit (mask-<session-id>.json) is found.
    p.add_argument("--session-id", default=os.environ.get("BENCH_RUN_ID", "demo10"))
    args = p.parse_args(argv)

    # A single --frameworks "a b" arg arrives as ["a b"]; split it.
    frameworks: list[str] = []
    for tok in args.frameworks:
        frameworks.extend(tok.split())
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    import yaml
    timeout = 180
    if args.task.exists():
        task_def = yaml.safe_load(args.task.read_text()) or {}
        timeout = int(task_def.get("timeout_seconds", 180))

    args.runs_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    cell_index = 0
    for fw in frameworks:
        for variant in variants:
            for seed in range(args.seeds):
                print(f"==> {fw} / {variant} / seed {seed}")
                row = _run_cell(
                    fw, variant, seed, cell_index, args.task, args.model_alias,
                    args.proxy_base_url, args.out_dir, args.spans_dir,
                    args.runs_dir, timeout, args.session_id)
                rows.append(row)
                cell_index += 1

    if args.merge_baseline:
        rows = _merge_baseline(rows, args.runs_dir)

    json_path, csv_path = _write_outputs(rows, args.runs_dir)
    _print_summary(rows)
    print(f"\nwrote {json_path}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
