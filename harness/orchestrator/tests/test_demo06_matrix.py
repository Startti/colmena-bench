import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import demo06_matrix as m  # noqa: E402


SIX_FW = {"colmena", "crewai", "langchain", "llamaindex", "langgraph", "google_adk"}


def test_matrix_shape():
    mat = m.CAPABILITY_MATRIX
    assert set(mat) == {"graph", "hitl_durable", "critic_retry", "masking"}
    assert set(m.FRAMEWORKS) == SIX_FW
    for feat in mat:
        assert set(mat[feat]) == SIX_FW


def test_colmena_native_on_all():
    # Colmena remains native on every capability.
    for feat, cells in m.CAPABILITY_MATRIX.items():
        assert cells["colmena"] == "native", feat


def test_langgraph_near_parity():
    # Round-2 finding: langgraph is native on graph/hitl_durable/critic_retry and
    # DIY only on masking.
    for feat in ("graph", "hitl_durable", "critic_retry"):
        assert m.CAPABILITY_MATRIX[feat]["langgraph"] == "native", feat
    assert m.CAPABILITY_MATRIX["masking"]["langgraph"] == "DIY"


def test_other_competitors_diy_on_all():
    # crewai / langchain / llamaindex / google_adk are DIY on every capability.
    for feat, cells in m.CAPABILITY_MATRIX.items():
        for fw in ("crewai", "langchain", "llamaindex", "google_adk"):
            assert cells[fw] == "DIY", (feat, fw)


def test_masking_native_only_for_colmena():
    # The universal differentiator: masking is native ONLY for colmena; all five
    # other frameworks (including langgraph) are DIY.
    cells = m.CAPABILITY_MATRIX["masking"]
    assert cells["colmena"] == "native"
    for fw in SIX_FW - {"colmena"}:
        assert cells[fw] == "DIY", fw


def test_render_markdown():
    md = m.render_markdown()
    assert ("| Feature | colmena | crewai | langchain | llamaindex | "
            "langgraph | google_adk |") in md
    assert "| masking | native | DIY | DIY | DIY | DIY | DIY |" in md
