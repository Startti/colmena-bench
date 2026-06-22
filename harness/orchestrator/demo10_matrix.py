"""Capability matrix for Demo #10 (secure secret collection): Colmena vs the field.

Every Python framework lets the LLM collect secrets — but they differ radically in
HOW the secret travels through the system. The six guarantees below are the
production-hardening properties that matter when a user hands you an API key:

  durable_pause    — suspend the agent mid-run, wait for a human to supply the
                     secret, then resume without losing context. LangGraph gets ✓
                     here via interrupt() + SqliteSaver checkpointer — it IS a real
                     near-peer for pause/resume.

  secret_never_reaches_llm — the secret value is encrypted into an opaque <sv_...>
                     handle BEFORE the LLM ever sees it. The LLM and the proxy
                     receive only the handle. Colmena ONLY.

  aes256_at_rest   — the handle is AES-256 encrypted at rest (SECURE_VALUES_KEY).
                     Colmena ONLY; every other framework stores or passes the
                     plaintext.

  auto_inject      — when the downstream tool (connect) runs, the engine
                     automatically decrypts the handle to the real value inside the
                     tool's execution context. No developer code needed. Colmena ONLY.

  echo_masking     — after the tool returns, the engine re-masks any secret value
                     that appears in the tool result BEFORE it re-enters the LLM
                     conversation (outbound scrub). Without this, the connect tool's
                     success response — which may echo the credential — reaches the
                     LLM. Colmena ONLY (via DagToolExecutor + secure:true node).

  batch_1_roundtrip — collect N secrets in a SINGLE suspend/resume round-trip.
                     Colmena's secure_suspend batches all 3 credential prompts in
                     one pause; hand-rolled implementations typically loop (N trips).
                     LangGraph can batch with care but requires imperative loop code.

HONEST FRAMING — LangGraph is the nearest peer:
  LangGraph's interrupt() gives genuine durable pause (cross-process with
  SqliteSaver), so it earns ✓ for durable_pause and ✓(impl) for batch_1_roundtrip
  (you CAN implement it, just not natively). The UNIVERSAL differentiator is
  secret_never_reaches_llm + echo_masking: these are the ONLY guarantees NO Python
  framework provides natively. Even if you hand-roll a secure channel in LangGraph,
  the LLM still sees the credential value unless you intercept the message stream —
  which the engine cannot do without native support.
"""
from __future__ import annotations

FRAMEWORKS = ["colmena", "langgraph", "crewai", "langchain", "llamaindex", "google_adk"]

# Values: "native" | "DIY" | "partial"
# "partial" = achievable with framework primitives but requires imperative dev code
CAPABILITY_MATRIX: dict[str, dict[str, str]] = {
    "durable_pause":             {
        "colmena":    "native",
        "langgraph":  "native",
        "crewai":     "DIY",
        "langchain":  "DIY",
        "llamaindex": "DIY",
        "google_adk": "DIY",
    },
    "secret_never_reaches_llm":  {
        "colmena":    "native",
        "langgraph":  "DIY",
        "crewai":     "DIY",
        "langchain":  "DIY",
        "llamaindex": "DIY",
        "google_adk": "DIY",
    },
    "aes256_at_rest":            {
        "colmena":    "native",
        "langgraph":  "DIY",
        "crewai":     "DIY",
        "langchain":  "DIY",
        "llamaindex": "DIY",
        "google_adk": "DIY",
    },
    "auto_inject":               {
        "colmena":    "native",
        "langgraph":  "DIY",
        "crewai":     "DIY",
        "langchain":  "DIY",
        "llamaindex": "DIY",
        "google_adk": "DIY",
    },
    "echo_masking":              {
        "colmena":    "native",
        "langgraph":  "DIY",
        "crewai":     "DIY",
        "langchain":  "DIY",
        "llamaindex": "DIY",
        "google_adk": "DIY",
    },
    "batch_1_roundtrip":         {
        "colmena":    "native",
        "langgraph":  "DIY",
        "crewai":     "DIY",
        "langchain":  "DIY",
        "llamaindex": "DIY",
        "google_adk": "DIY",
    },
}

# Human-readable labels for the matrix rows
FEATURE_LABELS: dict[str, str] = {
    "durable_pause":            "durable pause (mid-run suspend)",
    "secret_never_reaches_llm": "secret never reaches LLM",
    "aes256_at_rest":           "AES-256 encryption at rest",
    "auto_inject":              "auto-inject into downstream call",
    "echo_masking":             "outbound echo-masking",
    "batch_1_roundtrip":        "batch N secrets in 1 round-trip",
}


def get_matrix() -> dict[str, dict[str, str]]:
    """Return the capability matrix dict (feature -> framework -> value)."""
    return CAPABILITY_MATRIX


def render_markdown() -> str:
    """Return the matrix as a GitHub-flavoured Markdown table."""
    rows = [
        "| Feature | " + " | ".join(FRAMEWORKS) + " |",
        "|" + "---|" * (len(FRAMEWORKS) + 1),
    ]
    for feat, cells in CAPABILITY_MATRIX.items():
        label = FEATURE_LABELS.get(feat, feat)
        rows.append("| " + label + " | " + " | ".join(
            "✓" if cells[f] == "native" else ("~" if cells[f] == "DIY" else "✗")
            for f in FRAMEWORKS
        ) + " |")
    return "\n".join(rows)
