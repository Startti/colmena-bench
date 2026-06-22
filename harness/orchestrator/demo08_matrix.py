"""Capability matrix for Demo #8 (sandboxed code execution over a CSV).

Two axes, both verified live during the build (colmena develop @14beaba9):

DX (static, verified by reading each framework's idiomatic component):
- ``native_attach``  — attach a CSV and run model-written pandas over it as a
  built-in, declarative tool with the DataFrame pre-loaded. Colmena's
  ``attachment_run_python`` is native; the competitors require instantiating a
  specialized dataframe agent / vendoring a code interpreter (some shipped only in
  ``experimental`` packages) — DIY.
- ``safe_by_default`` — is model-generated code sandboxed WITHOUT an opt-in
  dangerous flag, a Docker daemon, or relying on the provider's server-side kernel?
  Colmena's ``restricted`` AST sandbox is in-process and declarative.

SECURITY (data-driven, from runs/demo08/summary.json — the controlled canary probe):
- ``blocks_file_read`` — did the framework's executor REFUSE the forbidden
  ``open(canary)`` snippet (``blocked``) or run it and leak the token (``leaked``)?
  Populated per-framework from the measured ``probe_controlled`` result.

The honest finding (see the doc): this is NOT "Colmena safe vs everyone unsafe".
2 of 5 competitors leak (the raw-``exec`` ones: langchain, langgraph); the rest
contain in heterogeneous ways (llamaindex library ``safe_eval``, crewai Docker,
google_adk Gemini server-side). Colmena is safe-by-default, declarative, in-process.
"""
from __future__ import annotations

import json
from pathlib import Path

FRAMEWORKS = ["colmena", "llamaindex", "langchain", "crewai", "langgraph", "google_adk"]

# DX axis — verified by reading each framework's idiomatic tabular component.
DX_MATRIX = {
    "native_attach":   {"colmena": "native", "llamaindex": "DIY", "langchain": "DIY",
                         "crewai": "DIY", "langgraph": "DIY", "google_adk": "DIY"},
    "safe_by_default": {"colmena": "native", "llamaindex": "library", "langchain": "no",
                         "crewai": "docker", "langgraph": "no", "google_adk": "server"},
}

REPO_ROOT = Path(__file__).resolve().parents[2]


def security_row(summary: list[dict]) -> dict[str, str]:
    """Per-framework controlled-probe result (blocked|leaked|skipped|error) read
    from the summary's ``probe`` rows."""
    out: dict[str, str] = {}
    for fw in FRAMEWORKS:
        rows = [r for r in summary if r.get("framework") == fw and r.get("mode") == "probe"]
        if not rows:
            out[fw] = "?"
        elif rows[0].get("skipped"):
            out[fw] = "skipped"
        else:
            out[fw] = str(rows[0].get("probe_controlled") or "?")
    return out


def load_summary() -> list[dict]:
    p = REPO_ROOT / "runs" / "demo08" / "summary.json"
    return json.loads(p.read_text()) if p.exists() else []


def render_markdown(summary: list[dict] | None = None) -> str:
    summary = summary if summary is not None else load_summary()
    sec = security_row(summary)
    rows = ["| Feature | " + " | ".join(FRAMEWORKS) + " |",
            "|" + "---|" * (len(FRAMEWORKS) + 1)]
    for feat, cells in DX_MATRIX.items():
        rows.append(f"| {feat} | " + " | ".join(cells[f] for f in FRAMEWORKS) + " |")
    rows.append("| blocks_file_read (probe) | " + " | ".join(sec[f] for f in FRAMEWORKS) + " |")
    return "\n".join(rows)


def main() -> int:
    print(render_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
