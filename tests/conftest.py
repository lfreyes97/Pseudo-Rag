import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.md").write_text(
        "El pacto de gracia es la base.\nDios prometió a Abraham.\nCristo cumple el pacto.\n\n"
        "Otra sección sobre la iglesia\ny los sacramentos.\n", encoding="utf-8")
    (d / "b.txt").write_text("Covenant theology and grace.\nThe covenant of works.\n", encoding="utf-8")
    return d


@pytest.fixture
def svc(tmp_path):
    """Servicio solo-texto (sin Chroma) sobre una carpeta de datos temporal."""
    from pseudo_rag.service import SearchService
    return SearchService(home=tmp_path / ".prag", create=True, semantic=False)
