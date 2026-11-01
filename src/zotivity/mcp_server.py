"""MCP-Server (stdio): stellt die Bibliothekssuche als Werkzeug für Claude Desktop & Co. bereit.

Eintrag in claude_desktop_config.json (Pfad zur Python-Umgebung anpassen):
    "zotivity": {"command": "C:/.../.venv/Scripts/python.exe", "args": ["-m", "zotivity", "mcp"]}

Das aufrufende Modell kann mehrfach mit eigenen Begriffen suchen, ganze
Auswertungsblätter lesen und Quellen mit Seitenzahl und Zotero-Link zitieren.
Die Suche läuft lokal; nur die zurückgegebenen Textstellen gehen an das Modell.
"""

from __future__ import annotations

import json

from zotivity.engine import Engine
from zotivity.index.store import SearchFilter
from zotivity.rag.sources import author_year, build_sources
from zotivity.retrieval import Searcher

INSTRUCTIONS = """Durchsucht die lokale Zotero-Bibliothek des Nutzers (wissenschaftliche Literatur, Deutsch und Englisch).
Suche mehrfach mit unterschiedlichen Begriffen in beiden Sprachen, bevor du antwortest. Zitiere mit Autor, Jahr und
Seite und gib den Zotero-Link an. Nutze get_sheet für strukturierte Auswertungen einzelner Texte, falls vorhanden."""


def build_server():
    from mcp.server import MCPServer

    engine = Engine()
    searcher = Searcher(engine)
    server = MCPServer("Zotivity", instructions=INSTRUCTIONS)

    @server.tool()
    def search_library(query: str, k: int = 10, collections: list[str] | None = None,
                       year_from: int | None = None, year_to: int | None = None) -> str:
        """Hybride Suche (Bedeutung + Stichworte) in den indexierten Volltexten.

        Args:
            query: Suchanfrage in natürlicher Sprache oder Stichworte (Deutsch oder Englisch).
            k: Anzahl Textstellen (1–50).
            collections: optional Sammlungs-IDs ("users/0:KEY") aus list_collections.
            year_from: optional frühestes Erscheinungsjahr.
            year_to: optional spätestes Erscheinungsjahr.
        """
        f = SearchFilter(collections=collections or [], year_from=year_from, year_to=year_to)
        hits = searcher.search(query, f, k=max(1, min(k, 50)))
        out = []
        for s in build_sources(engine.store, hits, 0, 10**9):
            d = s.as_dict()
            out.append({
                "citation": s.citation, "title": s.title, "page": s.page_label, "item_key": s.item_key,
                "zotero_link": d.get("zotero_pdf") or d["zotero_select"], "text": s.text,
            })
        return json.dumps(out, ensure_ascii=False, indent=1)

    @server.tool()
    def list_collections() -> str:
        """Sammlungen der Bibliothek mit IDs (für Filter in search_library)."""
        rows = []
        for lib in engine.settings.zotero.libraries:
            for c in engine.store.collections(lib):
                rows.append({"id": f"{lib}:{c['key']}", "name": c["name"], "parent": c["parent"]})
        return json.dumps(rows, ensure_ascii=False)

    @server.tool()
    def get_item(item_key: str, library: str = "users/0") -> str:
        """Metadaten und Abstract eines Eintrags."""
        it = engine.store.item(library, item_key)
        if not it:
            return "Nicht gefunden."
        return json.dumps({
            "citation": author_year(it), "title": it["title"], "year": it["year"], "type": it["item_type"],
            "publication": it["publication"], "doi": it["doi"], "abstract": it["abstract"], "tags": it["tags"],
        }, ensure_ascii=False)

    @server.tool()
    def get_sheet(item_key: str, library: str = "users/0") -> str:
        """Auswertungsblatt eines Textes (Fragestellung, Methode, Befunde, Kernzitate), falls bereits erstellt."""
        sheet = engine.store.get_sheet(library, item_key)
        return json.dumps(sheet["sheet"], ensure_ascii=False) if sheet else "Kein Auswertungsblatt vorhanden."

    return server


def run() -> None:
    build_server().run("stdio")
