"""End-to-End: simulierte Zotero-API → Abgleich → PDF-Extraktion → Embedding → Suche."""

from zotivity.index.indexer import Indexer
from zotivity.index.store import SearchFilter
from zotivity.jobs import Job
from zotivity.retrieval import Searcher, fts_query

TEEN = ("Jugendliche nutzen Chatbots wie ChatGPT zunehmend, um über persönliche Probleme, Einsamkeit "
        "und Stress zu sprechen. Die Befragung von 1200 Jugendlichen zeigt, dass emotionale Unterstützung "
        "das wichtigste Motiv ist. ")
SOCIAL = ("Social work practitioners use electronic information systems in child welfare. Managers shape "
          "discretion through documentation requirements and standardised assessment tools. ")
REFS = " ".join(f"Autor{i}, A. ({2000 + i}). Titel {i}. Zeitschrift, {i}(1), 1–9. doi:10.1/{i}" for i in range(14))


def build_library(fz):
    fz.add_collection("COLA0001", "KI und Jugend")
    fz.add_collection("COLB0002", "Soziale Arbeit")
    fz.add_collection("COLC0003", "Unterordner", parent="COLA0001")
    fz.add_item("ITEMA001", "Chatbots als Gesprächspartner", "Müller", "2024",
                abstract="Eine Studie zur Nutzung von Chatbots durch Jugendliche bei persönlichen Problemen " * 2,
                collections=["COLC0003"])
    fz.add_pdf("ATTA0001", "ITEMA001", [TEEN * 6, TEEN * 5, "Literatur\n\n" + REFS])
    fz.add_item("ITEMB001", "Information systems in social work", "Devlieghere", "2018", collections=["COLB0002"])
    fz.add_pdf("ATTB0001", "ITEMB001", [SOCIAL * 6, SOCIAL * 6])


def run_index(engine, **kw):
    job = Job("index", "test")
    return Indexer(engine).run(job, **kw), job


def test_full_pipeline(zengine, fake_zotero):
    build_library(fake_zotero)
    result, job = run_index(zengine)
    assert result["extracted"] == 2 and result["errors"] == 0
    st = zengine.store.stats(zengine.space())
    assert st["items"] == 2 and st["attachments_by_status"] == {"indexed": 2}
    # Literaturverzeichnis wird nicht eingebettet
    kinds = {r["kind"] for r in zengine.store.document_chunks("users/0", "ITEMA001")}
    assert "references" in kinds and "abstract" in kinds
    assert st["embedded"] == zengine.store.con.execute(
        "SELECT COUNT(*) FROM chunks WHERE kind != 'references'").fetchone()[0]

    s = Searcher(zengine)
    hits = s.search("Chatbots Jugendliche persönliche Probleme", k=5)
    assert hits and hits[0].chunk["item_key"] == "ITEMA001"
    text_hit = next(h for h in hits if h.chunk["kind"] == "text")
    assert text_hit.chunk["page_label"] in ("1", "2", "1–2")
    assert all(h.chunk["kind"] != "references" for h in hits)
    hits = s.search("electronic information systems child welfare", k=3)
    assert hits[0].chunk["item_key"] == "ITEMB001"


def test_collection_filter_includes_subcollections(zengine, fake_zotero):
    build_library(fake_zotero)
    run_index(zengine)
    s = Searcher(zengine)
    hits = s.search("information systems", SearchFilter(collections=["users/0:COLA0001"]), k=10)
    assert hits and {h.chunk["item_key"] for h in hits} == {"ITEMA001"}
    hits = s.search("Chatbots", SearchFilter(year_to=2020), k=10)
    assert {h.chunk["item_key"] for h in hits} <= {"ITEMB001"}


def test_incremental_sync_and_deletion(zengine, fake_zotero):
    build_library(fake_zotero)
    run_index(zengine)
    # Unverändert: nichts zu tun
    result, _ = run_index(zengine)
    assert result["extracted"] == 0
    # Geändertes PDF wird neu verarbeitet, gelöschter Eintrag entfernt
    fake_zotero.add_pdf("ATTB0001", "ITEMB001", [SOCIAL * 3 + " New findings on digital case files. " * 20])
    del fake_zotero.items["ITEMA001"]
    del fake_zotero.items["ATTA0001"]
    result, _ = run_index(zengine)
    assert result["extracted"] == 1
    assert result["synced"]["deleted"] == 2
    assert zengine.store.item("users/0", "ITEMA001") is None
    assert not zengine.store.document_chunks("users/0", "ITEMA001")
    hits = Searcher(zengine).search("digital case files", k=3)
    assert hits and all(h.chunk["item_key"] == "ITEMB001" for h in hits)


def test_snapshot_only_without_pdf(zengine, fake_zotero):
    # Schnappschuss mit ungeschlossenem <head> (wie Wiley-Seiten in Zotero)
    html = ("<html><head><title>Wiley</title><body>"
            + "".join(f"<p>Webseite Satz {i} über Kinderschutz und Algorithmen.</p>" for i in range(60))
            + "</body></html>")
    fake_zotero.add_item("ITEMS001", "Mit PDF und Schnappschuss", "Gillingham", "2019")
    fake_zotero.add_pdf("ATTS0001", "ITEMS001", [SOCIAL * 6])
    fake_zotero.add_snapshot("SNAP0001", "ITEMS001", html)
    fake_zotero.add_item("ITEMS002", "Nur Schnappschuss", "Muster", "2020")
    fake_zotero.add_snapshot("SNAP0002", "ITEMS002", html)
    run_index(zengine)
    st = zengine.store
    assert st.attachment("users/0", "ATTS0001")["status"] == "indexed"
    snap = st.attachment("users/0", "SNAP0001")
    assert snap["status"] == "redundant" and "PDF" in snap["error"]  # kein doppelter Text
    assert st.attachment("users/0", "SNAP0002")["status"] == "indexed"  # ohne PDF zählt der Schnappschuss
    assert any("Webseite Satz 59" in c["text"] for c in st.document_chunks("users/0", "ITEMS002"))
    assert st.errors() == [] and st.scope_stats(None, None)["documents"] == 2
    # Kommt eine PDF dazu, fliegt der bereits indexierte Schnappschuss wieder heraus
    fake_zotero.add_pdf("ATTS0002", "ITEMS002", [TEEN * 6])
    run_index(zengine)
    assert st.attachment("users/0", "SNAP0002")["status"] == "redundant"
    assert {c["att_key"] for c in st.document_chunks("users/0", "ITEMS002")} == {"ATTS0002"}
    # Fällt die PDF weg, wird der Schnappschuss wieder gelesen
    del fake_zotero.items["ATTS0001"]
    fake_zotero.version += 1
    run_index(zengine)
    assert st.attachment("users/0", "SNAP0001")["status"] == "indexed"


def test_collection_scope(zengine, fake_zotero):
    build_library(fake_zotero)
    for c in zengine.store.corpora():
        zengine.store.delete_corpus(c["id"])
    zengine.store.create_corpus("Soziale Arbeit", ["users/0:COLB0002"])
    result, _ = run_index(zengine)
    assert result["extracted"] == 1
    assert zengine.store.attachment("users/0", "ATTA0001")["status"] == "pending"


def test_progress_reports_each_document(zengine, fake_zotero):
    build_library(fake_zotero)
    result, job = run_index(zengine)
    p = job.counters
    assert p["docs_total"] == 2 and p["docs_done"] == 2
    assert p["current"] is None and p["eta"] == 0
    assert [r["status"] for r in p["recent"]] == ["indexed", "indexed"]
    titles = {r["title"] for r in p["recent"]}
    assert titles == {"Chatbots als Gesprächspartner", "Information systems in social work"}
    assert all(r["chunks"] > 0 and r["pages"] >= 2 for r in p["recent"])
    assert p["chunks_embedded"] == result["embedded"] > 0


def test_corpus_filter_and_stats(zengine, fake_zotero):
    build_library(fake_zotero)
    run_index(zengine)
    cid = zengine.store.create_corpus("KI", ["users/0:COLA0001"])
    hits = Searcher(zengine).search("information systems child welfare", zengine.make_filter({"corpus_id": cid}), k=5)
    assert {h.chunk["item_key"] for h in hits} == {"ITEMA001"}
    stats = zengine.store.scope_stats(Indexer(zengine).scope(corpus_id=cid), zengine.space())
    assert stats["documents"] == 1 and stats["indexed"] == 1 and stats["embedded"] == stats["chunks"] > 0
    empty = zengine.store.create_corpus("Leer", [])
    assert Searcher(zengine).search("Chatbots", zengine.make_filter({"corpus_id": empty}), k=5) == []


def test_existing_data_lands_in_default_project(tmp_path, monkeypatch):
    from zotivity.engine import Engine
    from zotivity.index.store import Store
    from zotivity.settings import SettingsStore

    monkeypatch.setenv("ZOTIVITY_HOME", str(tmp_path))
    store = Store(tmp_path / "i.sqlite3")
    cid = store.create_corpus("Projektgruppe", ["groups/1234567:*"])
    chat = store.create_chat("Frage")
    eng = Engine(SettingsStore(tmp_path / "s.json"), store)
    [p] = store.projects()
    assert p["name"] == "Allgemein" and p["corpus_ids"] == [cid] and p["chats"] == 1
    assert store.chat(chat)["project_id"] == p["id"]
    Engine(eng.settings_store, store)  # zweiter Start legt nichts doppelt an
    assert len(store.projects()) == 1


def test_filter_over_several_corpora_and_projects(zengine, fake_zotero):
    build_library(fake_zotero)
    run_index(zengine)
    a = zengine.store.create_corpus("A", ["users/0:COLA0001"])
    b = zengine.store.create_corpus("B", ["users/0:COLB0002"])
    one = zengine.store.allowed_items(zengine.make_filter({"corpus_ids": [a]}))
    both = zengine.store.allowed_items(zengine.make_filter({"corpus_ids": [a, b]}))
    assert one < both
    pid = zengine.store.create_project("Projekt")
    assert zengine.store.allowed_items(zengine.make_filter({"project_id": pid})) == set()  # noch kein Korpus
    zengine.store.assign_corpus(pid, b)
    assert zengine.store.allowed_items(zengine.make_filter({"project_id": pid})) == both - one


def test_fts_query_builder():
    q = fts_query('Jugendliche "und" ChatGPT-Nutzung 2023')
    assert '"jugendlich"*' in q and '"chatgpt"' in q and "und" not in q.split(" OR ")
    assert fts_query("der die das") == ""
