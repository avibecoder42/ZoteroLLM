"""Word (.docx) und OpenDocument (.odt): Text, Seitenzahlen der letzten Speicherung, Fussnoten, Änderungen, Tabellen."""
import json
import zipfile

from test_indexing_search import run_index

from zotivity.extract import extract_file
from zotivity.extract.office import DOCX_TYPE, ODT_TYPE
from zotivity.rag.sources import build_sources
from zotivity.retrieval.search import Searcher
from zotivity.settings import OFFICE_TYPES, SettingsStore

W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"')


def make_docx(path, body, footnotes="", endnotes=""):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f'<w:document {W_NS}><w:body>{body}</w:body></w:document>')
        if footnotes:
            z.writestr("word/footnotes.xml", f"<w:footnotes {W_NS}>{footnotes}</w:footnotes>")
        if endnotes:
            z.writestr("word/endnotes.xml", f"<w:endnotes {W_NS}>{endnotes}</w:endnotes>")
    return path


def p(*runs, ppr=""):
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def r(text):
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


BREAK = "<w:r><w:lastRenderedPageBreak/></w:r>"


def test_docx_pages_notes_changes_tables(tmp_path):
    body = (
        p(r("Erste Seite: Einleitung zur Studie.")),
        p(r("Satz auf Seite zwölf, "), BREAK, r("Fortsetzung auf Seite dreizehn."),
          '<w:r><w:footnoteReference w:id="2"/></w:r>'),
        p('<w:del w:id="1"><w:r><w:delText>gelöschter Satz</w:delText></w:r></w:del>',
          '<w:ins w:id="2">' + r("eingefügter Satz") + "</w:ins>"),
        "<w:tbl><w:tr><w:tc>" + p(r("Alter")) + "</w:tc><w:tc>" + p(r("Anteil")) + "</w:tc></w:tr></w:tbl>",
        p('<w:r><mc:AlternateContent><mc:Choice><w:drawing><w:txbxContent>' + p(r("Textfeld")) +
          "</w:txbxContent></w:drawing></mc:Choice><mc:Fallback><w:pict><w:txbxContent>" + p(r("Textfeld")) +
          "</w:txbxContent></w:pict></mc:Fallback></mc:AlternateContent></w:r>"),
        '<w:sectPr><w:pgNumType w:start="12"/></w:sectPr>',
    )
    notes = ('<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
             '<w:footnote w:id="2">' + p(r("Quelle der Zahlen.")) + "</w:footnote>")
    doc = extract_file(make_docx(tmp_path / "a.docx", "".join(body), notes), DOCX_TYPE)
    assert doc.method == "docx" and doc.label_source == "docx"
    assert [pg.label for pg in doc.pages] == ["12", "13"]
    assert doc.pages[0].text.endswith("Satz auf Seite zwölf,")
    second = doc.pages[1].text
    assert second.startswith("Fortsetzung auf Seite dreizehn.")
    assert "eingefügter Satz" in second and "gelöschter Satz" not in second
    assert "Alter | Anteil" in second
    assert second.count("Textfeld") == 1
    assert second.endswith("1 Quelle der Zahlen.")  # Fussnote am Ende ihrer Seite


def test_docx_sections_and_blank_page(tmp_path):
    body = "".join((
        p(r("Titelblatt"), ppr='<w:pPr><w:sectPr><w:pgNumType w:start="1"/></w:sectPr></w:pPr>'),
        p(BREAK, r("Hauptteil beginnt neu bei Seite eins.")),
        p(BREAK),  # leere Seite
        p(BREAK, r("Nach der Leerseite.")),
        '<w:sectPr><w:pgNumType w:start="1"/></w:sectPr>',
    ))
    doc = extract_file(make_docx(tmp_path / "b.docx", body), DOCX_TYPE)
    assert [(pg.label, pg.text) for pg in doc.pages] == [
        ("1", "Titelblatt"), ("1", "Hauptteil beginnt neu bei Seite eins."), ("3", "Nach der Leerseite.")]


def test_docx_without_saved_layout_has_no_page_numbers(tmp_path):
    body = "".join(p(r(f"Absatz {i} " + "Wort " * 120)) for i in range(40)) + "<w:sectPr/>"
    doc = extract_file(make_docx(tmp_path / "c.docx", body, endnotes=""), DOCX_TYPE)
    assert len(doc.pages) > 1 and all(pg.label == "" for pg in doc.pages)  # Belege mit „o. S.“
    assert "Absatz 39" in doc.pages[-1].text


ODT_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
          'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"')


def make_odt(path, body, styles=""):
    content = (f'<office:document-content {ODT_NS}><office:automatic-styles>{styles}</office:automatic-styles>'
               f"<office:body><office:text>{body}</office:text></office:body></office:document-content>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", ODT_TYPE)
        z.writestr("content.xml", content)
    return path


def test_odt_pages_breaks_notes(tmp_path):
    styles = ('<style:style style:name="P1" style:family="paragraph"><style:paragraph-properties '
              'fo:break-before="page" style:page-number="20"/></style:style>')
    body = (
        "<text:tracked-changes><text:changed-region><text:deletion><text:p>weg</text:p></text:deletion>"
        "</text:changed-region></text:tracked-changes>"
        "<text:table-of-content><text:index-body><text:p>Inhalt 1</text:p></text:index-body></text:table-of-content>"
        '<text:h text:outline-level="1">Einleitung</text:h>'
        "<text:p>Erster Teil<text:s text:c=\"2\"/>mit Abstand.</text:p>"
        "<text:p>Vor dem Umbruch <text:soft-page-break/>nach dem Umbruch"
        '<text:note text:note-class="footnote"><text:note-citation>1</text:note-citation>'
        "<text:note-body><text:p>Eine Fussnote.</text:p></text:note-body></text:note>.</text:p>"
        "<table:table><table:table-row><table:table-cell><text:p>A</text:p></table:table-cell>"
        "<table:table-cell><text:p>B</text:p></table:table-cell></table:table-row></table:table>"
        '<text:p text:style-name="P1">Neuer Teil auf Seite zwanzig.</text:p>'
    )
    doc = extract_file(make_odt(tmp_path / "d.odt", body, styles), ODT_TYPE)
    assert doc.method == "odt"
    assert [pg.label for pg in doc.pages] == ["1", "2", "20"]
    first, second, third = (pg.text for pg in doc.pages)
    assert first.startswith("Einleitung") and "Inhalt 1" not in first and "weg" not in first
    assert "Erster Teil mit Abstand." in first and first.endswith("Vor dem Umbruch")
    assert second.startswith("nach dem Umbruch.") and "A | B" in second and second.endswith("1 Eine Fussnote.")
    assert third == "Neuer Teil auf Seite zwanzig."


def test_odt_without_soft_breaks(tmp_path):
    doc = extract_file(make_odt(tmp_path / "e.odt", "<text:p>Nur ein Absatz ohne Seiten.</text:p>"), ODT_TYPE)
    assert [pg.label for pg in doc.pages] == [""] and doc.pages[0].text == "Nur ein Absatz ohne Seiten."


def test_settings_of_older_versions_read_word(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"version": 1, "indexing": {"content_types": ["application/pdf", "text/html"]}}))
    s = SettingsStore(path).get()
    assert s.version == 2 and s.indexing.content_types == ["application/pdf", "text/html", *OFFICE_TYPES]
    # Wer die Typen danach bewusst ändert, behält seine Wahl
    path.write_text(json.dumps({"version": 2, "indexing": {"content_types": ["application/pdf"]}}))
    assert SettingsStore(path).get().indexing.content_types == ["application/pdf"]


def test_word_attachment_indexed_and_cited_without_pdf_link(zengine, fake_zotero, tmp_path):
    fake_zotero.add_item("ITEMW001", "Bericht als Word-Datei", "Keller", "2025")
    body = "".join((p(r("Der Bericht beschreibt die Schulsozialarbeit im Kanton. " * 6)),
                    p(BREAK, r("Auf Seite zwei folgen die Empfehlungen zur Schulsozialarbeit. " * 6)),
                    "<w:sectPr/>"))
    fake_zotero.add_file("ATTW0001", "ITEMW001", make_docx(tmp_path / "bericht.docx", body), DOCX_TYPE)
    # Wie vor 0.9.0: Word nicht lesbar – der Anhang wird beim Abgleich übersprungen
    zengine.settings_store.update({"indexing": {"content_types": ["application/pdf"]}})
    run_index(zengine)
    assert zengine.store.attachment("users/0", "ATTW0001")["status"] == "skipped"
    # Nach dem Update: beim nächsten Abgleich vorgemerkt und gelesen
    zengine.settings_store.update({"indexing": {"content_types": ["application/pdf", *OFFICE_TYPES]}})
    result, _ = run_index(zengine)
    att = zengine.store.attachment("users/0", "ATTW0001")
    assert result["extracted"] == 1 and att["status"] == "indexed" and att["method"] == "docx"
    hits = Searcher(zengine).search("Empfehlungen zur Schulsozialarbeit", k=3)
    hit = next(h for h in hits if h.chunk["att_key"] == "ATTW0001")
    assert hit.chunk["page_label"] in ("2", "1–2")
    src = build_sources(zengine.store, [hit], 0, 10000)[0].as_dict()
    assert "zotero_pdf" not in src and src["zotero_select"].endswith("/ITEMW001")
