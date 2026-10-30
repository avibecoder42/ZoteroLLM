"""Recherche: Literatursuche von der Fragestellung bis zur Auswahl in Zotero.

Das Paket enthält die ganze Fachlogik (Quellen, Duplikate, Screening, Export, Protokoll) und importiert nichts aus
der App-Hülle. Nach aussen spricht es nur über die schmalen Schnittstellen in ``ports.py`` (Zotero, Schlüssel,
Sprachmodell). So lässt es sich später unverändert als Modul „Recherche“ in ZotLLM übernehmen: dort liefern die
vorhandenen Klassen (ZoteroClient, SecretStore, ChatModel) die Adapter, und ``api.install`` hängt die Schnittstelle
``/api/research/…`` an den bestehenden FastAPI-Server.

Innerhalb des Pakets nur relative Imports – dann kann es auch als ``zotllm.research`` liegen.
"""

__version__ = "0.1.0"
