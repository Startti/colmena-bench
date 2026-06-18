"""Capability matrix for Demo #4 (refund agent): native vs DIY.

Authored from the spec (docs/superpowers/specs/2026-06-17-demo06-refund-agent-...).
Each non-native cell corresponds to code the framework forces you to hand-roll,
which is what shows up in the imperative-LOC column. Verified during the build:
- Colmena: graph=node, HITL=`suspend` node, critic-retry=cyclic edge, masking=
  `secure: true` tool (engine `mask_outbound`). All declarative config.
- CrewAI/LangChain/LlamaIndex: each handler hand-rolled durable cross-process
  suspend (.state file), a critic-retry loop, and outbound tool-result masking;
  none expose these as native primitives (LangChain's interrupt + LlamaIndex's
  HITL event are in-process / LangGraph-only, not durable cross-process).
"""
from __future__ import annotations

FRAMEWORKS = ["colmena", "crewai", "langchain", "llamaindex"]

CAPABILITY_MATRIX = {
    "graph":        {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
    "hitl_durable": {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
    "critic_retry": {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
    "masking":      {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY"},
}


def render_markdown() -> str:
    rows = ["| Feature | " + " | ".join(FRAMEWORKS) + " |",
            "|" + "---|" * (len(FRAMEWORKS) + 1)]
    for feat, cells in CAPABILITY_MATRIX.items():
        rows.append(f"| {feat} | " + " | ".join(cells[f] for f in FRAMEWORKS) + " |")
    return "\n".join(rows)
