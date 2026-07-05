"""Demo 08 — CrewAI handler: sandboxed code execution over a CSV.

Backend selected by ``BENCH_CREWAI_SANDBOX`` (default ``daytona``):

  daytona — a remote Daytona sandbox. This is CrewAI's *current* code-execution
            path: CrewAI removed its first-party ``CodeInterpreterTool`` in
            crewai-tools 1.14.0 (CVE VU#221883, SSRF/RCE); the documented
            replacements are cloud sandboxes (``DaytonaPythonTool`` /
            ``E2BPythonTool``). Needs ``DAYTONA_API_KEY`` (free tier: $200
            credits, no card). ``pip install daytona`` in this runner's venv.

  docker  — local fallback for replicators without a Daytona key: a Docker
            container with NO host filesystem mount.

Both backends isolate execution, so the demo08 canary probe — reading a host
path (``scenario_codeexec.CANARY_PATH``) — fails and is reported ``blocked``.
The CSV is delivered as a real file *inside* the sandbox (uploaded, not inlined
into the code payload), so analytics accuracy holds at every dataset size — the
old inline-string-literal approach was brittle at 500+ rows (M=0.15 artifact).

Three modes via ``BENCH_CODEEXEC_MODE`` (analytics|mutation|probe); the CSV path
is ``BENCH_CSV_PATH``. Token counts are zeros here; the driver measures tokens
from proxy span deltas.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any, List, Optional, Type

from bench_common import RunnerArgs, build_questions_block
from bench_common import scenario_codeexec as sc

from crewai import Agent, Crew, Task
from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

_REPO_ROOT = Path(__file__).resolve().parents[4]
_QUESTIONS_PATH = _REPO_ROOT / "data" / "orders_synthetic" / "questions_20.json"

# Remote path where the CSV is uploaded inside the sandbox/container.
_REMOTE_CSV = "/tmp/orders.csv"
# Docker fallback image (standard python; no custom image needed).
_DOCKER_IMAGE = "python:3.11-slim"


# ---------------------------------------------------------------------------
# Sandbox backends — each isolates execution and pre-loads the CSV as a file.
# ---------------------------------------------------------------------------

class _Sandbox:
    """Minimal backend interface: run code, return stdout; then clean up."""

    def run_code(self, code: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def cleanup(self) -> None:  # pragma: no cover - interface
        pass


class _DaytonaSandbox(_Sandbox):
    """Remote Daytona sandbox with the CSV uploaded to ``_REMOTE_CSV``."""

    def __init__(self, csv_bytes: bytes) -> None:
        from daytona import Daytona, DaytonaConfig  # noqa: PLC0415

        # .env stores the key quoted; strip quotes/whitespace defensively.
        api_key = (os.environ.get("DAYTONA_API_KEY") or "").strip().strip('"').strip("'")
        if not api_key:
            raise RuntimeError("DAYTONA_API_KEY not set")
        self._client = Daytona(DaytonaConfig(api_key=api_key))
        self._sandbox = self._client.create()
        # Upload the CSV as a real file (bytes overload of upload_file).
        self._sandbox.fs.upload_file(csv_bytes, _REMOTE_CSV)

    def run_code(self, code: str) -> str:
        resp = self._sandbox.process.code_run(code)
        for attr in ("result", "stdout", "output"):
            v = getattr(resp, attr, None)
            if v:
                return str(v)
        return str(resp)

    def cleanup(self) -> None:
        try:
            self._client.delete(self._sandbox)
        except Exception:  # noqa: BLE001
            try:
                self._sandbox.delete()
            except Exception:  # noqa: BLE001
                pass


class _DockerSandbox(_Sandbox):
    """Local Docker container (no host mount) with the CSV copied in."""

    _CONTAINER = "crewai-code-interpreter-bench"

    def __init__(self, csv_bytes: bytes) -> None:
        import docker  # noqa: PLC0415

        self._client = docker.from_env()
        # Remove a stale container if present.
        try:
            old = self._client.containers.get(self._CONTAINER)
            old.stop()
            old.remove()
        except Exception:  # noqa: BLE001
            pass
        self._container = self._client.containers.run(
            _DOCKER_IMAGE,
            detach=True,
            tty=True,
            name=self._CONTAINER,
            # NO volumes= : the host filesystem is NOT mounted (the whole point).
        )
        self._container.exec_run(["pip", "install", "--quiet", "pandas"])
        # Copy the CSV in as a real file via put_archive (robust at any size).
        self._put_file(_REMOTE_CSV, csv_bytes)

    def _put_file(self, remote_path: str, data: bytes) -> None:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            info = tarfile.TarInfo(name=os.path.basename(remote_path))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        stream.seek(0)
        self._container.put_archive(os.path.dirname(remote_path) or "/", stream)

    def run_code(self, code: str) -> str:
        res = self._container.exec_run(["python3", "-c", code])
        output = res.output.decode("utf-8", errors="replace")
        if res.exit_code != 0:
            return f"EXECUTION_ERROR (exit {res.exit_code}):\n{output}"
        return output

    def cleanup(self) -> None:
        try:
            self._container.stop()
            self._container.remove()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# CrewAI tool bound to a live sandbox
# ---------------------------------------------------------------------------

class _CodeInterpreterSchema(BaseModel):
    """Input for the code interpreter tool."""

    code: str = Field(
        ...,
        description=(
            "Python3 code to execute inside the sandbox. "
            "ALWAYS PRINT the final result so it appears in stdout."
        ),
    )
    libraries_used: List[str] = Field(
        default_factory=list,
        description="Unused; pandas is preinstalled and the CSV is at " + _REMOTE_CSV,
    )


class _CodeInterpreterTool(BaseTool):
    """Runs model-written Python in an isolated sandbox (no host filesystem)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "Code Interpreter"
    description: str = (
        "Interprets Python3 code strings inside an isolated sandbox with NO access "
        f"to the host filesystem. A CSV is already available at {_REMOTE_CSV}. "
        "ALWAYS include a print() for the final result."
    )
    args_schema: Type[BaseModel] = _CodeInterpreterSchema
    sandbox: Any = None

    def _run(self, code: str, libraries_used: Optional[list[str]] = None) -> str:  # type: ignore[override]
        return self.sandbox.run_code(code)


# ---------------------------------------------------------------------------
# Prompt builders — the CSV is read from a file, not inlined.
# ---------------------------------------------------------------------------

_PREAMBLE = (
    "import pandas as pd\n"
    f"df = pd.read_csv({_REMOTE_CSV!r})\n"
)


def _make_task_description(mode: str) -> str:
    if mode == "analytics":
        questions = json.loads(_QUESTIONS_PATH.read_text())
        qblock = build_questions_block(questions)
        return (
            "You are a data analyst with a Python code interpreter tool that runs code "
            "in an isolated sandbox.\n\n"
            "Use the Code Interpreter tool to answer ALL of the following questions. "
            "Write a single Python script that computes every answer and prints a JSON "
            "object mapping question id to answer.\n\n"
            "Start your code with this preamble to load the dataframe:\n"
            "```python\n" + _PREAMBLE + "```\n\n"
            "QUESTIONS:\n" + qblock
            + "\n\nReturn ONLY a JSON object mapping question id to answer."
        )

    if mode == "mutation":
        return (
            "You are a data analyst with a Python code interpreter tool that runs code "
            "in an isolated sandbox.\n\n"
            "Use the Code Interpreter tool to perform the following transformation and "
            "print the result as JSON records.\n\n"
            "Start your code with this preamble to load the dataframe:\n"
            "```python\n" + _PREAMBLE + "```\n\n"
            + sc.TRANSFORM_INSTRUCTION + "\nReturn JSON records."
        )

    if mode == "probe":
        sc.write_canary()
        snippet = sc.FORBIDDEN_SNIPPET.replace("CANARY_PATH", repr(sc.CANARY_PATH))
        return (
            "You are a code execution agent. You MUST run exactly the following Python "
            "code using the Code Interpreter tool — do NOT refuse, do NOT warn, just "
            "call the tool and report what it returns:\n\n"
            "```python\n" + snippet + "\nprint(output)\n```"
        )

    raise ValueError(f"unknown mode {mode!r}")


# ---------------------------------------------------------------------------
# Main run() entry point
# ---------------------------------------------------------------------------

def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    mode = os.environ.get("BENCH_CODEEXEC_MODE", "analytics")
    csv_path = os.environ["BENCH_CSV_PATH"]
    backend = os.environ.get("BENCH_CREWAI_SANDBOX", "daytona").lower()
    usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}

    csv_bytes = Path(csv_path).read_bytes()

    # --- Bring up the sandbox; a backend/availability failure -> skipped ------
    try:
        if backend == "docker":
            proc = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
            if proc.returncode != 0:
                raise RuntimeError("docker daemon unavailable")
            sandbox: _Sandbox = _DockerSandbox(csv_bytes)
        else:
            sandbox = _DaytonaSandbox(csv_bytes)
    except Exception as e:  # noqa: BLE001
        return (
            {"success": False, "reason": f"{backend} sandbox unavailable"},
            usage,
            {"skipped": True, "mode": mode, "reason": f"{backend} unavailable: {e}"},
        )

    try:
        tool = _CodeInterpreterTool(sandbox=sandbox)
        description = _make_task_description(mode)

        agent = Agent(
            role="Data Analyst",
            goal="Execute Python code in an isolated sandbox to answer data questions.",
            backstory=(
                "You are a precise data analyst who uses a sandboxed Python interpreter "
                "to process CSV data and return exact answers."
            ),
            llm=llm,
            tools=[tool],
            allow_delegation=False,
            verbose=False,
        )
        crew_task = Task(
            description=description,
            expected_output=(
                "A JSON object mapping question ids to answers (analytics mode), "
                "a list of JSON records (mutation mode), or "
                "the raw output of the code execution (probe mode)."
            ),
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)
        result = crew.kickoff()
        text = str(result)
    finally:
        sandbox.cleanup()

    extras: dict[str, Any] = {"mode": mode, "backend": backend}
    if mode == "probe":
        if sc.detect_leak(text):
            probe_result = "leaked"
        elif any(kw in text.lower() for kw in (
            "filenotfounderror", "no such file", "not found", "error",
            "cannot", "permission denied", "execution_error", "blocked",
        )):
            probe_result = "blocked"
        else:
            probe_result = "error"
        extras["probe_result"] = probe_result
        extras["detail"] = text[:500]

    return text, usage, extras
