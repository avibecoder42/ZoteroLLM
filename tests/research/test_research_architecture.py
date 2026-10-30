"""Architektur-Regeln aus dem Konzept (3.4): Das Paket zotllm.research importiert nichts von ZotLLM (oder der früheren
eigenständigen Hülle) und nutzt untereinander nur relative Imports – so bleibt es mit der eigenständigen Recherche-App
austauschbar. Die Verbindung zu ZotLLM liegt allein in research_adapters.py."""

from __future__ import annotations

import ast
from pathlib import Path

RESEARCH = Path(__file__).resolve().parents[2] / "src" / "zotllm" / "research"
ALLOWED_THIRD_PARTY = {"httpx", "fastapi", "pydantic"}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield 0, a.name
        elif isinstance(node, ast.ImportFrom):
            yield node.level, node.module or ""


def test_research_is_self_contained():
    import sys

    stdlib = set(sys.stdlib_module_names)
    files = list(RESEARCH.rglob("*.py"))
    assert len(files) > 20
    for f in files:
        for level, mod in _imports(f):
            if level:  # relativ: innerhalb des Pakets
                continue
            top = mod.split(".")[0]
            assert top != "zotllm", f"{f.name} importiert ZotLLM (nur relative Imports, Adapter in research_adapters.py)"
            assert top not in ("research", "litsearch_app"), f"{f.name}: innerhalb des Pakets nur relative Imports"
            assert top in stdlib or top in ALLOWED_THIRD_PARTY or top == "__future__", f"{f.name}: unerwarteter Import {mod}"


def test_api_paths_under_prefix():
    from zotllm.research.api import PREFIX, make_router
    from zotllm.research.service import ResearchService

    assert PREFIX == "/api/research"
    router = make_router(ResearchService.__new__(ResearchService))
    assert all(r.path.startswith(PREFIX) for r in router.routes)
