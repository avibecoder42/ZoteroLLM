"""Schmale Schnittstellen nach aussen (Konzept 3.4).

Das Paket erreicht Zotero, Schlüssel und Sprachmodell nur hierüber. In der eigenständigen App liefert die Hülle
einfache Implementierungen, in ZotLLM die vorhandenen Klassen:

- ``KeyStore``  → ``zotllm.keystore.SecretStore`` (hat ``get(name)``)
- ``ChatModel`` → ``zotllm.llm.ChatModel`` (hat ``complete_json(system, prompt)``)
- ``ZoteroPort`` → lokal ein dünner Adapter um ``zotllm.zotero.ZoteroClient``; Web-API über ``zotero_web.py``

Bibliotheken heissen wie in ZotLLM: ``users/0`` ist die eigene Bibliothek (auch über die Web-API, der Adapter setzt
die User-ID ein), ``groups/<ID>`` eine Gruppe.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

# Namen im Schlüsselspeicher
KEY_ZOTERO_WEB = "zotero-web"   # API-Schlüssel der Zotero-Web-API (zotero.org/settings/keys)
KEY_NCBI = "ncbi"               # optional: 10 statt 3 Anfragen pro Sekunde an PubMed
KEY_OPENALEX = "openalex"       # seit Februar 2026 nötig (kostenloses Konto)
KEY_SEMANTICSCHOLAR = "semanticscholar"  # ohne Schlüssel oft überlastet

MY_LIBRARY = "users/0"


@runtime_checkable
class KeyStore(Protocol):
    def get(self, name: str) -> str | None: ...


@runtime_checkable
class ChatModel(Protocol):
    """Für die KI-Vorschläge (Phase 2b). Ans Modell gehen nur Titel und Abstract bzw. der Projekttext, nie Volltexte.

    ``schema`` ist ein JSON-Schema für die Antwort; ein Adapter ohne strukturierte Ausgaben darf es ignorieren (die
    Antwort wird ohnehin geprüft). ``label`` nennt Anbieter und Modell fürs Protokoll; ``usage`` (optional) zählt Token.
    """

    label: str

    def complete_json(self, system: str, prompt: str, schema: dict | None = None) -> object: ...


@runtime_checkable
class ZoteroPort(Protocol):
    backend: str  # "web" | "local"

    def status(self) -> dict:
        """{"ok": bool, "message": str, ...} – darf nicht werfen."""
        ...

    def can_write(self, lib: str) -> bool:
        """Schreibrecht für diese Bibliothek (Web: Rechte des Schlüssels; lokal: Freigabe in Zotero)."""
        ...

    def libraries(self) -> list[dict]:
        """[{"lib": "users/0" | "groups/123", "name": str}]"""
        ...

    def collections(self, lib: str) -> list[dict]:
        """[{"key": str, "name": str, "parent": str | None}]"""
        ...

    def iter_items(self, lib: str) -> Iterator[dict]:
        """Einträge oberster Ebene im Format der Zotero-API: {"key", "version", "data": {...}}."""
        ...

    def create_collection(self, lib: str, name: str, parent: str | None = None) -> str: ...

    def create_items(self, lib: str, items: list[dict]) -> list[dict]:
        """Je Eintrag {"key": str} oder {"key": None, "error": str}, in derselben Reihenfolge."""
        ...

    def add_to_collection(self, lib: str, collection_key: str, item_keys: list[str]) -> int: ...
