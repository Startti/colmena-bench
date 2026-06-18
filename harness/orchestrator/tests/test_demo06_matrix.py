import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import demo06_matrix as m  # noqa: E402


def test_matrix_shape():
    mat = m.CAPABILITY_MATRIX
    assert set(mat) == {"graph", "hitl_durable", "critic_retry", "masking"}
    for feat in mat:
        assert set(mat[feat]) == {"colmena", "crewai", "langchain", "llamaindex"}


def test_colmena_native_competitors_diy():
    for feat, cells in m.CAPABILITY_MATRIX.items():
        assert cells["colmena"] == "native", feat
        for fw in ("crewai", "langchain", "llamaindex"):
            assert cells[fw] == "DIY", (feat, fw)


def test_render_markdown():
    md = m.render_markdown()
    assert "| Feature | colmena | crewai | langchain | llamaindex |" in md
    assert "| masking | native | DIY | DIY | DIY |" in md
