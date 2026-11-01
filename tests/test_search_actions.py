"""Suchen: Literaturnachweise und Kurzbelege der Auswahl im Zitierstil, Export (BibTeX, RIS, Word, Markdown) und
Ablage in einer Zotero-Sammlung."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_indexing_search import build_library, run_index

H = {"X-Zotivity": "1"}
BOTH = [{"lib": "users/0", "key": "ITEMA001"}, {"lib": "users/0", "key": "ITEMB001"}]


@pytest.fixture
def api(zengine, fake_zotero, monkeypatch):
    build_library(fake_zotero)
    run_index(zengine)
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        yield c


def test_copy_references_and_short_citations(api):
    r = api.post("/api/library/cite", json={"items": BOTH + [BOTH[0]]}, headers=H).json()
    assert r["count"] == 2 and r["from_zotero"] and r["style_title"]
    lines = r["bibliography"]["text"].splitlines()
    # Literaturverzeichnis aus Zotero (die Reihenfolge bestimmt dort der Stil; die Simulation sortiert nicht)
    assert len(lines) == 2 and {x.split(",")[0] for x in lines} == {"Devlieghere", "Müller"}
    assert "<i>Information systems in social work</i>" in r["bibliography"]["html"]
    assert r["short"].startswith("(") and r["short"].index("Devlieghere") < r["short"].index("Müller")
    assert len(r["shorts"]) == 2
    one = api.post("/api/library/cite", json={"items": BOTH[:1]}, headers=H).json()
    assert one["count"] == 1 and one["bibliography"]["text"].startswith("Müller")
    assert api.post("/api/library/cite", json={"items": []}, headers=H).status_code == 400
    assert api.post("/api/library/cite", json={"items": [{"lib": "users/0", "key": "GIBTSNICHT"}]},
                    headers=H).status_code == 400


def test_bibliography_from_several_libraries_is_sorted(zengine, monkeypatch):
    """Zotero sortiert je Bibliothek; über eigene Bibliothek und Gruppen hinweg ordnet Zotivity zusammen."""
    from zotivity.exporting import Citations

    def load(self, zot, by_lib):
        self.bib_html = ["Zeller, A. (2020). <i>Z</i>.", "Meier, B. (2019). <i>M</i>.", "Arnold, C. (2021). <i>A</i>."]

    monkeypatch.setattr(Citations, "_load_from_zotero", load)
    cit = Citations(zengine, [("users/0", "K1"), ("groups/1", "K2"), ("groups/1", "K3")], "apa", "de")
    assert [x.split(",")[0] for x in cit.bibliography_text()] == ["Arnold", "Meier", "Zeller"]


def test_unavailable_zotero_is_remembered_briefly():
    """Geschlossenes Zotero: nicht bei jedem Kopieren erneut verbinden (unter Windows je rund 2 s)."""
    import httpx

    from zotivity.zotero import ZoteroClient

    calls = []
    up = {"on": False}

    def handle(request):
        calls.append(request.url.path)
        if not up["on"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={}, headers={"Zotero-Server-ID": "S"})

    zot = ZoteroClient("http://127.0.0.1:9", keystore=object(), transport=httpx.MockTransport(handle))
    assert zot.is_available() is False and zot.is_available() is False and len(calls) == 1
    up["on"] = True
    assert zot.is_available(fresh=True) is True and len(calls) == 2  # Hintergrundplaner: immer neu prüfen
    assert zot.is_available() is True and len(calls) == 3  # erreichbar: nichts gemerkt


def export(api, fmt):
    r = api.post("/api/library/export", json={"items": BOTH, "format": fmt}, headers=H)
    assert r.status_code == 200, r.text
    meta = r.json()
    f = api.get(f"/api/library/export/{meta['token']}")
    assert f.status_code == 200
    assert api.get(f"/api/library/export/{meta['token']}").status_code == 404  # nur einmal abholbar
    return meta["filename"], f


def test_exports(api):
    name, f = export(api, "bib")
    assert name.endswith(".bib") and f.text.count("@article") == 2
    name, f = export(api, "ris")
    assert name.endswith(".ris") and f.text.count("TY  - JOUR") == 2 and f.text.count("ER  - ") == 2
    assert "AU  - Devlieghere, A." in f.text and f.text.index("Devlieghere") < f.text.index("Müller")
    name, f = export(api, "md")
    assert f.text.startswith("# Literaturliste") and "## Literatur" in f.text
    name, f = export(api, "docx")
    xml = zipfile.ZipFile(io.BytesIO(f.content)).read("word/document.xml").decode("utf-8")
    assert xml.count("ADDIN ZOTERO_ITEM CSL_CITATION") == 2 and "ADDIN ZOTERO_BIBL" in xml
    assert api.post("/api/library/export", json={"items": BOTH, "format": "pdf"}, headers=H).status_code == 400


def test_file_in_zotero_collection(api, zengine, fake_zotero):
    body = {"items": BOTH + [{"lib": "users/0", "key": "ITEMA001"}], "lib": "users/0", "new_name": "Kapitel 2"}
    # Ohne Schreibzugriff: verständliche Meldung
    r = api.post("/api/library/to-collection", json=body, headers=H)
    assert r.status_code == 403 and r.json()["kind"] == "zotero_auth"
    zengine.zotero().authorize()
    r = api.post("/api/library/to-collection", json=body, headers=H).json()
    assert r["added"] == 2 and r["skipped"] == 0 and r["select"].startswith("zotero://select/library/collections/")
    assert r["collection"] in fake_zotero.items["ITEMA001"]["data"]["collections"]
    again = api.post("/api/library/to-collection", json={"items": BOTH, "lib": "users/0",
                                                         "collection": r["collection"]}, headers=H).json()
    assert again["added"] == 0 and again["already"] == 2
    assert api.post("/api/library/to-collection", json={"items": BOTH, "lib": "groups/1", "new_name": "x"},
                    headers=H).status_code == 400
    assert api.post("/api/library/to-collection", json={"items": BOTH, "lib": "users/0"}, headers=H).status_code == 400
