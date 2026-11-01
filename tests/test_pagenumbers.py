"""Gedruckte Seitenzahlen: Erkennung aus Kopf-/Fusszeilen, Seitenwechsel in Abschnitten, Seiten der Kernzitate,
Umstellung bestehender Auswertungsblätter und Forschungsstände („o. S.“ ohne Seitenzahlen)."""

from fakes import make_pdf
from test_indexing_search import run_index

from zotivity.extract import extract_file
from zotivity.extract.chunker import chunk_pages
from zotivity.extract.pagenumbers import detect_page_labels, parse_page_range
from zotivity.extract.pdf import PageText
from zotivity.rag import ReviewService
from zotivity.rag.review import NO_PAGE, PAGES_VERSION, page_at, parse_citation


def test_pdf_labels_from_hex_strings():
    """PyMuPDF gibt Beschriftungen aus PDF-Hex-Text teils roh zurück („<FEFF0032>“ = „2“)."""
    from zotivity.extract.pagenumbers import clean_pdf_label

    assert clean_pdf_label("<FEFF0032>") == "2" and clean_pdf_label("<feff0069 0076>") == "iv"
    assert clean_pdf_label("<FEFF0037>–<FEFF0038>") == "7–8" and clean_pdf_label("<3132>") == "12"
    assert clean_pdf_label("þÿ\x002") == "2" and clean_pdf_label("S12") == "S12" and clean_pdf_label(None) == ""
    # Roh sahen die Beschriftungen anders aus als die Dateiseite und wurden übernommen – lesbar sind es nur
    # die Dateiseiten, die nichts aussagen: keine Seitenzahlen
    raw = [f"<FEFF00{ord(str(i + 1)):02X}>" for i in range(4)]
    assert detect_page_labels([[]] * 4, [clean_pdf_label(x) for x in raw]) == (["", "", "", ""], "")


def test_hex_labels_are_cleaned_in_existing_index(tmp_path):
    import json
    import sqlite3

    from zotivity.index.store import Store

    store = Store(tmp_path / "i.sqlite3")
    with store.write() as con:
        con.execute("DELETE FROM meta WHERE key='hex_labels_fixed'")
        con.execute("INSERT INTO attachments(lib, key, parent, status, page_labels) VALUES('users/0','ATT1','IT1','indexed',?)",
                    (json.dumps(["<FEFF0031>", "<FEFF0032>"]),))
        con.execute("INSERT INTO chunks(lib, item_key, att_key, ord, kind, page_label, text) VALUES('users/0','IT1','ATT1',0,'text',?,'x')",
                    ("<FEFF0037>–<FEFF0038>",))
        con.execute("INSERT INTO chat_messages(chat_id, role, content, sources) VALUES(1,'assistant','a',?)",
                    (json.dumps([{"n": 1, "page_label": "<FEFF0032>"}]),))
        con.execute("INSERT INTO sheets(lib, item_key, sheet) VALUES('users/0','IT1',?)",
                    (json.dumps({"kernzitate": [{"zitat": "z", "seite": "<FEFF0032>"}]}),))
    store.close()
    store = Store(tmp_path / "i.sqlite3")
    con = sqlite3.connect(tmp_path / "i.sqlite3")
    assert con.execute("SELECT page_labels, status FROM attachments").fetchone() == ('["1", "2"]', "pending")
    assert con.execute("SELECT page_label FROM chunks").fetchone()[0] == "7–8"
    assert json.loads(con.execute("SELECT sources FROM chat_messages").fetchone()[0])[0]["page_label"] == "2"
    assert json.loads(con.execute("SELECT sheet FROM sheets").fetchone()[0])["kernzitate"][0]["seite"] == "2"
    con.close()
    store.close()


def test_parse_page_range():
    assert parse_page_range("114–126") == (114, 126)
    assert parse_page_range("114-26") == (114, 126)
    assert parse_page_range("5") == (5, 5)
    assert parse_page_range("e1234") is None and parse_page_range("") is None


def test_offset_from_footers_ignores_volume_and_year():
    # Seite 0 (Artikelbeginn) ohne sichtbare Zahl; Kopfzeile „Vol. 28 (2019)“ auf jeder Seite
    cands = [[("a", 28), ("a", 2019)] + ([("a", 114 + i)] if i else []) for i in range(13)]
    labels, source = detect_page_labels(cands)
    assert source == "kopfzeile" and labels[0] == "114" and labels[12] == "126"


def test_cover_page_outside_zotero_range_gets_no_number():
    # Deckblatt eines Portals, dann S. 114 (ohne sichtbare Zahl), S. 115 … 126
    cands = [[], []] + [[("a", 113 + i)] for i in range(2, 14)]
    labels, _ = detect_page_labels(cands, page_range=(114, 126))
    assert labels[0] == "" and labels[1] == "114" and labels[13] == "126"
    # ohne Spanne aus Zotero: eine Seite vor der Folge wird ergänzt, das Deckblatt davor nicht
    labels, _ = detect_page_labels([[], []] + [[("a", 113 + i)] for i in range(2, 14)])
    assert labels[0] == "" and labels[1] == "114"


def test_competing_portal_numbering_loses_to_journal_pages():
    cands = [[("a", i + 1), ("a", 14), ("a", 200 + i)] for i in range(14)]  # „Seite 3 von 14“ + Heftseiten
    labels, _ = detect_page_labels(cands)
    assert labels[:2] == ["200", "201"]


def test_roman_front_matter_and_fallbacks():
    cands = [[("r", i + 1)] for i in range(4)] + [[("a", i + 1)] for i in range(6)]
    labels, _ = detect_page_labels(cands)
    assert labels == ["i", "ii", "iii", "iv", "1", "2", "3", "4", "5", "6"]
    # Ohne Zahlen am Rand: Beschriftungen der PDF nur, wenn sie mehr sagen als 1, 2, 3 …
    none = [[] for _ in range(3)]
    assert detect_page_labels(none, pdf_labels=["1", "2", "3"]) == (["", "", ""], "")
    assert detect_page_labels(none, pdf_labels=["45", "46", "47"]) == (["45", "46", "47"], "pdf")
    # … sonst die Spanne laut Zotero, wenn die Seitenzahl der Datei genau passt
    assert detect_page_labels(none, page_range=(10, 12)) == (["10", "11", "12"], "zotero")
    assert detect_page_labels(none, page_range=(10, 20))[0] == ["", "", ""]


def test_pdf_extraction_reads_printed_numbers(tmp_path):
    text = "Ein Absatz mit Inhalt über Kinderschutz und Algorithmen in der Sozialen Arbeit. " * 12
    pdf = make_pdf(tmp_path / "artikel.pdf", [text] * 5, first_page=114, header="Child Abuse Review Vol. 28 (2019)",
                   unnumbered=(0,))
    doc = extract_file(pdf, "application/pdf")
    assert [p.label for p in doc.pages] == ["114", "115", "116", "117", "118"] and doc.label_source == "kopfzeile"
    assert "Child Abuse Review" not in doc.pages[2].text  # Kopfzeile bleibt aus dem Text draussen
    plain = extract_file(make_pdf(tmp_path / "bericht.pdf", [text] * 3, first_page=None), "application/pdf")
    assert [p.label for p in plain.pages] == ["", "", ""]  # ohne Seitenzahlen → o. S.


def test_chunks_record_page_breaks():
    pages = [PageText(index=i, label=str(114 + i), text=f"Seite {i} Satz eins. Seite {i} Satz zwei.") for i in range(3)]
    [chunk] = chunk_pages(pages, chunk_tokens=400, overlap_tokens=10, min_chunk_tokens=1)
    assert chunk.page_label == "114–116" and len(chunk.breaks) == 2
    row = {"page_start": chunk.page_start, "page_breaks": __import__("json").dumps(chunk.breaks)}
    assert page_at(row, chunk.text.index("Seite 1 Satz zwei")) == 1
    assert page_at(row, chunk.text.index("Seite 2 Satz eins")) == 2


def test_no_page_citation_is_parsed():
    assert parse_citation("@ABCD1234, o. S.; @EFGH5678, S. 12") == [("ABCD1234", NO_PAGE), ("EFGH5678", "12")]


FIRST = "Einleitung zum Kinderschutz und zur Rolle von Entscheidungshilfen in der Praxis der Jugendhilfe. " * 8
SECOND = "Die Befragung zeigt, dass Fachkräfte algorithmischen Prognosen nur mit grosser Vorsicht vertrauen. " * 8


def _review_with_sheet(zengine, quote_page: str):
    store = zengine.store
    rid = store.create_review("T", "Frage", {"sections": [{"heading": "B", "text": (
        "## B\n\nLaut Studie „Fachkräfte algorithmischen Prognosen nur mit grosser Vorsicht vertrauen“ "
        f"[@ITEMP001, S. {quote_page}].")}]})
    store.put_review_docs(rid, [{"lib": "users/0", "item_key": "ITEMP001", "included": True}])
    store.put_sheet("users/0", "ITEMP001", {"kernzitate": [
        {"zitat": "Fachkräfte algorithmischen Prognosen nur mit grosser Vorsicht vertrauen", "seite": quote_page}]},
        "test")
    return rid


def test_quote_pages_and_conversion_of_existing_review(zengine, fake_zotero):
    fake_zotero.add_item("ITEMP001", "Algorithmen im Kinderschutz", "Gillingham", "2019")
    fake_zotero.add_pdf("ATTP0001", "ITEMP001", [FIRST, SECOND, FIRST], first_page=114, unnumbered=(0,))
    run_index(zengine)
    assert zengine.store.page_labels("users/0", "ATTP0001") == ["114", "115", "116"]
    # Vorhandenes Blatt und Text mit Dateiseite „2“ (alter Stand) → gedruckte Seite 115
    rid = _review_with_sheet(zengine, "2")
    svc = ReviewService(zengine)
    cites: list[dict] = []
    md = svc.render(rid, body_only=True, link_target="dialog", cites=cites)
    assert "Gillingham 2019, S. 115" in md and cites[0]["pdf_page"] == 2
    sheet = zengine.store.get_sheet("users/0", "ITEMP001")["sheet"]
    q = sheet["kernzitate"][0]
    assert q["seite"] == "115" and q["pdf_seite"] == 2 and sheet["_seiten"] == PAGES_VERSION
    assert zengine.store.get_review(rid)["state"]["_seiten_ok"] == ["ITEMP001"]
    # Ein zweites Anzeigen rechnet nicht noch einmal um
    assert "S. 115" in svc.render(rid, body_only=True, link_target="dialog")


def test_document_without_page_numbers_gives_o_s(zengine, fake_zotero):
    fake_zotero.add_item("ITEMP001", "Bericht ohne Seitenzahlen", "Muster", "2021")
    fake_zotero.add_pdf("ATTP0001", "ITEMP001", [FIRST, SECOND], first_page=None)
    run_index(zengine)
    rid = _review_with_sheet(zengine, "2")
    svc = ReviewService(zengine)
    cites: list[dict] = []
    md = svc.render(rid, body_only=True, link_target="dialog", cites=cites)
    assert "Muster 2021, o. S." in md
    assert cites[0]["no_page"] and cites[0]["pdf_page"] == 2  # Link führt trotzdem an die Fundstelle
    # Seitenmarken für das Auswertungsblatt: [o. S.] statt Dateiseiten
    text, _ = svc.document_text("users/0", "ITEMP001", None, 100000, 10)
    assert "[o. S.]" in text and "[S. 1]" not in text


def test_reindex_keeps_embeddings_when_text_is_unchanged(zengine, fake_zotero):
    fake_zotero.add_item("ITEMP001", "Algorithmen", "Gillingham", "2019")
    fake_zotero.add_pdf("ATTP0001", "ITEMP001", [FIRST, SECOND], first_page=114)
    run_index(zengine)
    con = zengine.store.con
    before = con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE att_key='ATTP0001' ORDER BY ord")]
    zengine.store.set_attachment_status("users/0", "ATTP0001", "pending")
    result, _ = run_index(zengine)
    assert result["extracted"] == 1 and result["embedded"] == 0  # nur neu gelesen, nichts neu eingebettet
    assert [r[0] for r in con.execute("SELECT id FROM chunks WHERE att_key='ATTP0001' ORDER BY ord")] == ids
    assert con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == before
