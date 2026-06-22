"""Orchestrator entry point — loads a task YAML and runs N reps per framework.

Skeleton for T08. Real subprocess execution + retries land in T18 when at
least one runner exists. For now this:

  - Validates the task YAML against `schemas/task.schema.json`.
  - Resolves the runner binary path per framework.
  - Builds the CLI invocation per `runner_contract.md`.
  - Dry-runs by default (prints the planned command). `--execute` actually
    forks the subprocess (will fail until T12/T13 land).

Usage (dry-run):
    python -m orchestrator.run --task ../tasks/01_hello_world.yaml \\
        --framework colmena --n 1
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterable

import typer
import yaml
from jsonschema import Draft202012Validator

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent
SCHEMAS_DIR = HARNESS_DIR / "schemas"
TASK_SCHEMA = json.loads((SCHEMAS_DIR / "task.schema.json").read_text())

FRAMEWORKS = ("colmena", "crewai", "langchain", "langgraph", "google_adk", "llamaindex")

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _runner_command(framework: str) -> list[str]:
    """Map framework name → CLI invocation prefix for its runner."""
    match framework:
        case "colmena":
            return [str(REPO_ROOT / "runners/colmena/target/release/colmena-bench-runner")]
        case _:
            return [
                "python",
                "-m",
                "runner",
                # Each Python runner exposes `python -m runner` as its entry
                # point (declared in its own pyproject); the orchestrator
                # changes PYTHONPATH per framework to pick the right one.
            ]


def _env_for(framework: str, run_id: str, proxy_base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["BENCH_RUN_ID"] = run_id
    env["LITELLM_PROXY_BASE_URL"] = proxy_base_url
    env.setdefault("LITELLM_PROXY_API_KEY", "sk-bench-runner-do-not-use-in-prod")
    runner_dir = REPO_ROOT / "runners" / framework
    if framework != "colmena":
        env["PYTHONPATH"] = f"{runner_dir}:{env.get('PYTHONPATH', '')}"
    return env


def _validate_task(task_path: Path) -> dict:
    raw = yaml.safe_load(task_path.read_text())
    Draft202012Validator(TASK_SCHEMA).validate(raw)
    return raw


def _plan_runs(
    task: dict,
    framework: str,
    variant: str,
    n: int,
    proxy_base_url: str,
    output_dir: Path,
) -> Iterable[dict]:
    for _ in range(n):
        run_id = str(uuid.uuid4())
        output_path = output_dir / framework / f"{run_id}.json"
        cmd = _runner_command(framework) + [
            "--task", str(task["__path"]),
            "--variant", variant,
            "--run-id", run_id,
            "--model-alias", task.get("model_alias", "gemini-2.5-flash"),
            "--proxy-base-url", proxy_base_url,
            "--output", str(output_path),
            "--timeout-seconds", str(task.get("timeout_seconds", 300)),
        ]
        yield {
            "run_id": run_id,
            "cmd": cmd,
            "output_path": output_path,
            "env": _env_for(framework, run_id, proxy_base_url),
        }


@app.command()
def main(
    task: Path = typer.Option(..., exists=True, readable=True),
    framework: str = typer.Option(..., help=f"One of {FRAMEWORKS}"),
    variant: str = typer.Option("default"),
    n: int = typer.Option(1, min=1, max=200),
    proxy_base_url: str = typer.Option("http://127.0.0.1:4000"),
    output_dir: Path = typer.Option(Path("results/latest/raw")),
    execute: bool = typer.Option(
        False, "--execute", help="Actually fork the runner. Default is dry-run."
    ),
) -> None:
    if framework not in FRAMEWORKS:
        raise typer.BadParameter(f"--framework must be one of {FRAMEWORKS}")
    task_data = _validate_task(task)
    task_data["__path"] = task
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / framework).mkdir(parents=True, exist_ok=True)

    for plan in _plan_runs(task_data, framework, variant, n, proxy_base_url, output_dir):
        if not execute:
            typer.echo(json.dumps({"would_run": plan["cmd"], "run_id": plan["run_id"]}))
            continue
        # Real execution path — wired up in T18.
        result = subprocess.run(
            plan["cmd"],
            env=plan["env"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=task_data.get("timeout_seconds", 300) + 5,
            check=False,
        )
        stderr_path = plan["output_path"].with_suffix(".stderr")
        stderr_path.write_bytes(result.stderr)
        if result.returncode != 0:
            typer.echo(
                f"[{plan['run_id']}] runner exit {result.returncode} — see {stderr_path}",
                err=True,
            )


if __name__ == "__main__":
    app()
