"""Colmena runner entry — `python -m runner`. Thin wrapper over bench_common."""
from __future__ import annotations

import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from bench_common import run

from .llm import build_llm
from .tasks import (
    task01,
    task04_expert,
    task04_naive,
    task05,
    task06_refund,
    task07_tools,
    task07b_tools,
    task08_codeexec,
    task09_skills,
    task10_secrets,
)


def _provenance() -> "str | None":
    """The Colmena engine's git tag/SHA — unambiguous build provenance.

    The pip version (`colmena-ai` == 0.4.0) is identical across engine builds
    (e.g. `14beaba9` and tag `v0.9.0` both report 0.4.0), so it alone cannot say
    which engine a run used. Prefer the build-time stamp `runners/colmena/
    COLMENA_BUILD.txt` written by setup_all.sh right after `maturin develop`
    (reflects the COMPILED commit); fall back to a live `git describe` of the
    checkout at $COLMENA_REPO (or the default sibling `../colmena`). Returns None
    if neither is available (provenance then stays the bare pip version)."""
    stamp = Path(__file__).resolve().parents[1] / "COLMENA_BUILD.txt"
    if stamp.exists():
        val = stamp.read_text().strip()
        if val:
            return val
    repo_root = Path(__file__).resolve().parents[3]
    candidates = []
    if os.environ.get("COLMENA_REPO"):
        candidates.append(os.environ["COLMENA_REPO"])
    candidates.append(str(repo_root.parent / "colmena"))  # default sibling checkout
    for repo in candidates:
        try:
            out = subprocess.run(
                ["git", "-C", repo, "describe", "--tags", "--always", "--dirty"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:  # noqa: BLE001 — git absent / not a repo → next candidate
            continue
    return None


def _version() -> str:
    # Colmena's Python package is `colmena-ai`; enrich the (build-indistinct) pip
    # version with the engine's git tag/SHA so every summary is unambiguous (A-2).
    pip = "unknown"
    for dist in ("colmena-ai", "colmena"):
        try:
            pip = metadata.version(dist)
            break
        except metadata.PackageNotFoundError:
            continue
    prov = _provenance()
    return f"{pip}+git:{prov}" if prov else pip


HANDLERS = {
    "01_hello_world": task01.run,
    "04_csv_naive": task04_naive.run,
    "04_csv_expert": task04_expert.run,
    "05_context_scrubbing": task05.run,
    "06_refund": task06_refund.run,
    "07_tools": task07_tools.run,
    "07b_tools_session": task07b_tools.run,
    "08_codeexec": task08_codeexec.run,
    "09_skills": task09_skills.run,
    "10_secrets": task10_secrets.run,
}

if __name__ == "__main__":
    sys.exit(run("colmena", _version, build_llm, HANDLERS))
