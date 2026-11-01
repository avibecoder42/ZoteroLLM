"""Dubletten: dasselbe Werk als mehrere Zotero-Einträge – Erkennung, Regel, nur die gewählte Kopie wird gelesen und
gefunden (auch in Korpora, die nur eine andere Kopie enthalten), Entscheidungen von Hand und über die API."""

from fastapi.testclient import TestClient
from test_indexing_search import TEEN, build_library, run_index

from zotivity.index import duplicates
from zotivity.index.duplicates import find_groups, normalize_doi, title_key
from zotivity.retrieval import Searcher

H = {"X-Zotivity": "1"}


def row(lib, key, title, author="Müller", year=2024, doi="", extra="", item_type="journalArticle"):
    return {"lib": lib, "key": key, "item_type": item_type, "title": title, "year": year, "doi": doi, "extra": extra,
            "creators": [{"lastName": author, "firstName": "A."}]}


def test_detection_rules():
    assert normalize_doi("https://doi.org/10.3389/FPSYG.2026.123.") == "10.3389/fpsyg.2026.123"
    assert title_key("Editorial", [{"lastName": "X"}], 2020) == ""  # zu kurz: nur über die DOI
    assert title_key("Die adaptive ökologische Falle", [{"lastName": "Gong"}], 2026) == \
        "die adaptive okologische falle|gong|2026"
    groups = find_groups([
        row("users/0", "A", "The adaptive ecological trap", doi="10.1234/abc"),
        row("groups/1", "B", "The Adaptive Ecological Trap!", doi=""),  # ohne DOI: über Titel/Autor/Jahr dazu
        row("groups/1", "C", "Ganz anderer Titel hier", extra="tex.x: y\nDOI: 10.1234/ABC"),  # DOI im Feld Extra
        row("users/0", "D", "Editorial", author="X", year=2020),
        row("groups/1", "E", "Editorial", author="X", year=2020),  # kurzer Titel ohne DOI: nicht zusammengefasst
        row("users/0", "F", "Preprint und Artikel gleich", doi="10.1234/pre"),
        row("groups/1", "G", "Preprint und Artikel gleich", doi="10.1234/art"),  # verschiedene DOIs: nicht zusammen
        row("users/0", "H", "Soziale Arbeit digital heute"),
        row("groups/1", "I", "Soziale Arbeit digital heute"),
        row("groups/1", "J", "Soziale Arbeit digital heute", year=2023),  # anderes Jahr
        row("users/0", "K", "Anhang ohne Eintrag hier", item_type="attachment"),
        row("groups/1", "L", "Anhang ohne Eintrag hier", item_type="attachment"),
    ])
    assert groups == {
        "doi:10.1234/abc": [("groups/1", "B"), ("groups/1", "C"), ("users/0", "A")],
        "t:soziale arbeit digital heute|muller|2024": [("groups/1", "I"), ("users/0", "H")],
    }


def test_rule_prefers_text_then_pages_then_library():
    q = {("users/0", "A"): (1, 0), ("groups/1", "B"): (1, 0)}
    assert duplicates.rule_choice(list(q), q, "users/0") == ("users/0", "A")
    assert duplicates.rule_choice(list(q), q, "groups/1") == ("groups/1", "B")
    q[("users/0", "A")] = (0, 0)  # gelesen, aber ohne Text
    assert duplicates.rule_choice(list(q), q, "users/0") == ("groups/1", "B")
    q = {("users/0", "A"): (2, 0), ("groups/1", "B"): (2, 1)}  # beide gelesen, nur B mit Seitenzahlen
    assert duplicates.rule_choice(list(q), q, "users/0") == ("groups/1", "B")


def add_copy(fz):
    """Zweite Kopie von „Chatbots als Gesprächspartner“ in der Sammlung „Soziale Arbeit“ (eigene PDF)."""
    fz.add_item("ITEMD001", "Chatbots als Gesprächspartner", "Müller", "2024", collections=["COLB0002"])
    fz.add_pdf("ATTD0001", "ITEMD001", [TEEN * 4, "Zweite Seite der Kopie. " * 30])


def test_only_the_chosen_copy_is_read_and_found(zengine, fake_zotero):
    build_library(fake_zotero)
    add_copy(fake_zotero)
    result, job = run_index(zengine)
    work = next(iter(zengine.store.duplicate_groups()))
    assert zengine.store.duplicate_groups()[work] == [("users/0", "ITEMA001"), ("users/0", "ITEMD001")]
    # Lauf ohne Rückfrage: Regel übernommen (Gleichstand → kleinerer Schlüssel), die andere Kopie nicht gelesen
    assert job.counters["duplicates_auto"] == 1 and zengine.store.duplicate_choices()[work]["mode"] == "rule"
    assert result["extracted"] == 2
    assert zengine.store.attachment("users/0", "ATTD0001")["status"] == "pending"
    st = zengine.store.scope_stats(zengine.resolve_copies(zengine.store.allowed_items(
        zengine.make_filter({"corpus_id": zengine.store.corpora()[0]["id"]}))), zengine.space())
    assert st["documents"] == 2 and st["pending"] == 0  # die nicht gewählte Kopie zählt nicht als offen

    # Korpus nur mit der anderen Kopie: das Werk gehört dazu – über die gewählte Kopie
    cid = zengine.store.create_corpus("Soziale Arbeit", ["users/0:COLB0002"])
    from zotivity.index.indexer import Indexer

    assert Indexer(zengine).scope(corpus_id=cid) == {("users/0", "ITEMB001"), ("users/0", "ITEMA001")}
    assert Indexer(zengine).scope(corpus_id=cid, resolve=False) == {("users/0", "ITEMB001"), ("users/0", "ITEMD001")}
    hits = Searcher(zengine).search("Chatbots Jugendliche persönliche Probleme", zengine.make_filter({"corpus_id": cid}))
    assert hits and {h.chunk["item_key"] for h in hits} <= {"ITEMA001", "ITEMB001"}
    assert hits[0].chunk["item_key"] == "ITEMA001"

    # Von Hand die andere Kopie wählen: der nächste Lauf liest sie, Treffer kommen nur noch von ihr
    zengine.store.set_duplicate_choice(work, "user", "users/0", "ITEMD001")
    result, job = run_index(zengine)
    assert result["extracted"] == 1 and job.counters["duplicates_auto"] == 0
    assert zengine.store.attachment("users/0", "ATTD0001")["status"] == "indexed"
    hits = Searcher(zengine).search("Chatbots Jugendliche persönliche Probleme", k=10)
    keys = {h.chunk["item_key"] for h in hits}
    assert "ITEMD001" in keys and "ITEMA001" not in keys

    # Keine Dublette: beide Kopien werden verwendet
    zengine.store.set_duplicate_choice(work, "separate")
    assert zengine.copy_resolution() == {}
    keys = {h.chunk["item_key"] for h in Searcher(zengine).search("Chatbots Jugendliche persönliche Probleme", k=10)}
    assert {"ITEMA001", "ITEMD001"} <= keys


def test_duplicates_api(zengine, fake_zotero, monkeypatch):
    build_library(fake_zotero)
    add_copy(fake_zotero)
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        # Vor dem ersten Lauf: Bibliothek noch nie abgeglichen → sync=1 gleicht vorher ab
        r = c.get("/api/duplicates?undecided=1&sync=1").json()
        assert r["ask"] is True and r["preferred"] == "users/0" and r["libraries"][0]["lib"] == "users/0"
        (g,) = r["groups"]
        assert g["mode"] is None and g["title"] == "Chatbots als Gesprächspartner" and len(g["copies"]) == 2
        a, d = g["copies"]
        assert a["key"] == "ITEMA001" and a["rule"] and a["chosen"] and a["text"] == 1
        assert a["collections"] == ["KI und Jugend › Unterordner"] and d["collections"] == ["Soziale Arbeit"]
        assert c.post("/api/duplicates/choices", json={"choices": [
            {"work": g["work"], "mode": "user", "lib": "users/0", "key": "ITEMX"}]}, headers=H).status_code == 400
        assert c.post("/api/duplicates/choices", json={"choices": [
            {"work": g["work"], "mode": "user", "lib": "users/0", "key": "ITEMD001"}]}, headers=H).json()["saved"] == 1
        assert c.get("/api/duplicates?undecided=1").json()["groups"] == []
        (g,) = c.get("/api/duplicates").json()["groups"]
        assert g["mode"] == "user" and [x["chosen"] for x in g["copies"]] == [False, True]
        # Entscheidung zurücknehmen: gilt wieder als neu
        c.post("/api/duplicates/choices", json={"choices": [{"work": g["work"], "mode": None}]}, headers=H)
        assert len(c.get("/api/duplicates?undecided=1").json()["groups"]) == 1
