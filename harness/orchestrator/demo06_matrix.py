"""Capability matrix for Demo #4 (refund agent): native vs DIY.

Authored from the spec (docs/superpowers/specs/2026-06-17-demo06-refund-agent-...).
Each non-native cell corresponds to code the framework forces you to hand-roll,
which is what shows up in the imperative-LOC column. Verified during the build:
- Colmena: graph=node, HITL=`suspend` node, critic-retry=cyclic edge, masking=
  `secure: true` tool (engine `mask_outbound`). All declarative config — native on
  all four.
- CrewAI/LangChain/LlamaIndex/Google ADK: each handler hand-rolled durable
  cross-process suspend (.state file), a critic-retry loop, and outbound
  tool-result masking; none expose these as native primitives.

ROUND-2 FINDING (langgraph + google_adk added):
- LangGraph is the honest NEAR-PEER. Its `StateGraph` is a real graph, and
  `interrupt()` + a file-backed `SqliteSaver` checkpointer give genuinely native
  durable, cross-process HITL; the graph loop is its native critic-retry. So
  langgraph is native on graph / hitl_durable / critic_retry — only masking is DIY.
- Outbound secret masking is the UNIVERSAL DIFFERENTIATOR: it is the ONLY feature
  NO Python framework provides natively (not even LangGraph). Colmena alone makes
  forgetting to scrub unable to leak the secret. The honest differentiation vs the
  strongest competitor (LangGraph) therefore narrows to masking.
"""
from __future__ import annotations

FRAMEWORKS = ["colmena", "crewai", "langchain", "llamaindex", "langgraph", "google_adk"]

CAPABILITY_MATRIX = {
    "graph":        {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY", "langgraph": "native", "google_adk": "DIY"},
    "hitl_durable": {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY", "langgraph": "native", "google_adk": "DIY"},
    "critic_retry": {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY", "langgraph": "native", "google_adk": "DIY"},
    "masking":      {"colmena": "native", "crewai": "DIY", "langchain": "DIY", "llamaindex": "DIY", "langgraph": "DIY",    "google_adk": "DIY"},
}


def render_markdown() -> str:
    rows = ["| Feature | " + " | ".join(FRAMEWORKS) + " |",
            "|" + "---|" * (len(FRAMEWORKS) + 1)]
    for feat, cells in CAPABILITY_MATRIX.items():
        rows.append(f"| {feat} | " + " | ".join(cells[f] for f in FRAMEWORKS) + " |")
    return "\n".join(rows)
