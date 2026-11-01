"""Suche in der Zotero-Bibliothek, Einträge in Korpora, Texte je Korpus, Vorschau, Schreibzugriff."""

from test_server import H, client  # noqa: F401 - Fixture

from zotivity.jobs import Job
from zotivity.library_search import CatalogQuery, fts_expression, search_catalog


def test_fts_expression():
    assert fts_expression("digit lern") == '"digit"* AND "lern"*'
    assert fts_expression('"soziale arbeit" -schule') == '("soziale arbeit") NOT "schule"*'
    assert fts_expression("chatbot ODER agent") == '("chatbot"* OR "agent"*)'
    assert fts_expression("-nur") is None and fts_expression("  ") is None


def test_catalog_search_fields_filters_and_locations(client):
    def search(**q):
        return client.post("/api/library/search", json={"query": q}, headers=H).json()

    r = search(q="chatbots")
    assert r["total"] == 1 and r["results"][0]["key"] == "ITEMA001"
    hit = r["results"][0]
    # Fundort: Bibliothek und Sammlungspfad, je mit Link zum Auswählen in Zotero
    assert hit["library"] == "Meine Bibliothek" and hit["index_status"] == "indexed" and hit["pdf"]
    paths = [loc["path"] for loc in hit["locations"]]
    assert "Meine Bibliothek › KI und Jugend › Unterordner" in paths
    assert any("/collections/COLC0003/items/ITEMA001" in loc["select"] for loc in hit["locations"])
    # Mehrfeld: Autor + Jahresbereich
    assert search(creator="devlieghere")["results"][0]["key"] == "ITEMB001"
    assert search(creator="devlieghere", year_from=2019)["total"] == 0
    assert search(year_from=2020, year_to=2030)["total"] == 1
    # Sammlung inkl. Untersammlungen, Volltext der indexierten Texte mit Textausschnitt
    assert [x["key"] for x in search(collections=["users/0:COLA0001"])["results"]] == ["ITEMA001"]
    ft = search(fulltext="information systems")
    assert ft["results"][0]["key"] == "ITEMB001" and "\u0001" in ft["results"][0]["snippet"]
    assert search(q="")["total"] == 0


def test_add_search_hits_to_corpus_and_documents_panel(client):
    cid = client.post("/api/corpora", json={"name": "Auswahl", "sources": ["users/0:COLA0001"]}, headers=H).json()["id"]
    c = client.post(f"/api/corpora/{cid}/items", json={"items": [{"lib": "users/0", "key": "ITEMB001"}]},
                    headers=H).json()
    assert "users/0:@ITEMB001" in c["sources"]
    info = next(s for s in c["sources_info"] if s["kind"] == "item")
    assert info["label"].startswith("Information systems")
    assert c["stats"]["documents"] == 2  # Sammlung + einzelner Eintrag
    docs = client.get(f"/api/corpora/{cid}/documents").json()
    assert {d["item_key"] for d in docs["indexed"]} == {"ITEMA001", "ITEMB001"} and docs["pending"] == []
    assert docs["indexed"][0]["select"].startswith("zotero://select/")
    # Treffer zeigen, in welchen Korpora des Projekts sie sind
    pid = client.get("/api/projects").json()["projects"][0]["id"]
    client.put(f"/api/projects/{pid}/corpora/{cid}", json={"assigned": True}, headers=H)
    r = client.post("/api/library/search", json={"query": {"q": "information"}, "project_id": pid}, headers=H).json()
    assert r["results"][0]["corpora"] == [cid]


def test_corpus_preview_counts_texts_before_indexing(client):
    r = client.post("/api/corpora/preview", json={"sources": ["users/0:*"]}, headers=H).json()
    assert r["stats"]["documents"] == 2 and r["unsynced"] == []
    r = client.post("/api/corpora/preview", json={"sources": ["groups/99:*"]}, headers=H).json()
    assert r["unsynced"] == ["groups/99"]


def test_catalog_sync_job(zengine, fake_zotero):
    from test_indexing_search import build_library

    from zotivity.index.indexer import Indexer

    build_library(fake_zotero)
    summary = Indexer(zengine).sync_catalog(Job("catalog", "t"))
    assert summary["libraries"] == 1 and summary["items"] >= 2
    assert zengine.store.get_meta("catalog_synced_at")
    res = search_catalog(zengine.store, CatalogQuery(title="chatbots"))
    assert res["total"] == 1


def test_catalog_follows_zotero_changes(zengine, fake_zotero, monkeypatch):
    """Versionsvergleich mit Zotero: geänderte Bibliothek erkennen, nach zwei Minuten selbst abgleichen."""
    import time

    from test_indexing_search import build_library

    from zotivity import service
    from zotivity.index.indexer import Indexer

    build_library(fake_zotero)
    idx = Indexer(zengine)
    assert idx.catalog_changes() == ["users/0"]  # noch nie abgeglichen
    idx.sync_catalog(Job("catalog", "t"))
    assert idx.catalog_changes() == []
    fake_zotero.add_item("ITEMC001", "Neuer Eintrag", "Neu", "2025")
    assert idx.catalog_changes() == ["users/0"]

    sched = service.BackgroundScheduler(zengine)
    sched.zotero_running = True
    started = []
    monkeypatch.setattr(zengine.jobs, "start", lambda kind, title, fn, group=None: started.append(kind))
    now = time.time()
    sched._follow_catalog(now)  # Änderung erkannt, der letzte Abgleich ist aber erst eben gewesen
    assert sched.catalog_changed == ["users/0"] and not started
    sched._follow_catalog(now + 130)
    assert started == ["catalog"] and sched.catalog_changed == []
    sched.zotero_running = False
    sched._follow_catalog(now + 300)
    assert sched.catalog_changed == [] and started == ["catalog"]


def test_catalog_changes_in_group_without_versions(engine, tmp_path, monkeypatch):
    """Gruppen melden in Zotero 10 lokal keine Version: neue Einträge zeigt die Zahl der Einträge."""
    from fakes import FakeZotero

    from zotivity import keystore
    from zotivity.index.indexer import Indexer
    from zotivity.zotero import ZoteroClient

    fz = FakeZotero(tmp_path / "storage", lib="groups/77", versioned=False)
    fz.add_item("GRPA0001", "Gruppeneintrag", "Gruppe", "2020")
    client = ZoteroClient("http://127.0.0.1:23119", keystore=keystore.get_store(), transport=fz.transport())
    monkeypatch.setattr(engine, "zotero", lambda: client)
    idx = Indexer(engine)
    assert idx.library_changed(client, "groups/77")  # noch nie abgeglichen
    idx.sync_metadata(Job("catalog", "t"), libraries=["groups/77"])
    assert engine.store.library_state("groups/77")["items_total"] == 1
    assert not idx.library_changed(client, "groups/77")
    fz.add_item("GRPA0002", "Zweiter Eintrag", "Gruppe", "2021")
    assert idx.library_changed(client, "groups/77")


def test_outdated_plugin_is_reported(client):
    def step():
        return next(s for s in client.get("/api/setup").json()["steps"] if s["id"] == "plugin")

    assert not step()["done"]
    # Plugins bis 1.0.1 hiessen „ZotLLM“: altes entfernen, neues installieren
    client.get("/api/plugin/info?client=zotero-plugin&version=1.0.1")
    s = step()
    assert not s["done"] and "heisst jetzt Zotivity" in s["detail"] and "„ZotLLM“" in s["detail"]
    client.get("/api/plugin/info?client=zotero-plugin&version=1.1.0")
    assert step()["done"]


def test_session_write_key_counts_as_access(zengine, fake_zotero):
    fake_zotero.remember = False
    zot = zengine.zotero()
    assert not zot.has_write_access()
    assert zot.authorize() and zot.has_write_access()
    zot.revoke_local()
    assert not zot.has_write_access()
