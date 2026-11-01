"""Word (.docx) und OpenDocument-Text (.odt, LibreOffice): Text mit den Seitenumbrüchen der letzten Speicherung.

Beide Formate sind ZIP-Archive mit XML. Seiten: Word schreibt beim Speichern <w:lastRenderedPageBreak/> an jeden
Seitenanfang, LibreOffice <text:soft-page-break/> an jeden automatischen Umbruch (harte Umbrüche stehen dort in den
Absatzformaten). Fehlen diese Angaben (z. B. Export aus Google Docs), hat das Dokument keine Seitenzahlen („o. S.“).

Gelesen werden Haupttext, Überschriften, Listen und Tabellen; Fuss- und Endnoten stehen am Ende ihrer Seite bzw. des
Dokuments. Bei nachverfolgten Änderungen gilt der aktuelle Stand (Gelöschtes fehlt). Kopf- und Fusszeilen, Kommentare
und Verzeichnisse (Inhaltsverzeichnis, Register) bleiben weg.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from zotivity.extract.pdf import ExtractedDoc, PageText, text_as_document

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ODT_TYPE = "application/vnd.oasis.opendocument.text"
MAX_XML_BYTES = 200 * 1024 * 1024  # entpackt; schützt vor beschädigten oder präparierten Archiven

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
STYLE = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
FO = "{urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0}"

_WS = re.compile(r"\s+")


def _read_xml(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise ValueError(f"{name} ist zu gross ({info.file_size // (1024 * 1024)} MB entpackt)")
    return ET.fromstring(z.read(info))


class _Pages:
    """Sammelt Absätze seitenweise. Ein Umbruch auf einer noch leeren Seite (z. B. Leerseite) zählt nur die
    Seitenzahl weiter, statt eine leere Seite anzulegen."""

    def __init__(self, start: int, max_pages: int):
        self.paras: list[list[str]] = [[]]
        self.numbers = [start]
        self.buf: list[str] = []
        self.notes: list[list[str]] = [[]]  # Fussnoten je Seite, erscheinen am Seitenende
        self.restart: int | None = None
        self.max_pages = max_pages

    def text(self, s: str) -> None:
        self.buf.append(s)

    def end_para(self) -> None:
        t = _WS.sub(" ", "".join(self.buf)).strip()
        self.buf = []
        if t:
            self.paras[-1].append(t)

    def page_break(self) -> None:
        self.end_para()
        number = self.restart if self.restart is not None else self.numbers[-1] + 1
        self.restart = None
        if not self.paras[-1] and not self.notes[-1]:
            if any(self.paras) or len(self.paras) > 1:  # Leerseite mitten im Dokument
                self.numbers[-1] = number
            return
        if len(self.paras) >= self.max_pages:
            return
        self.paras.append([])
        self.notes.append([])
        self.numbers.append(number)

    def note(self, text: str) -> None:
        text = _WS.sub(" ", text).strip()
        if text:
            self.notes[-1].append(text)

    def document(self, method: str, paged: bool, endnotes: list[str]) -> ExtractedDoc:
        self.end_para()
        if endnotes:
            self.notes[-1].extend(endnotes)
        pages = [paras + notes for paras, notes in zip(self.paras, self.notes)]
        if not paged:
            return text_as_document("\n\n".join(p for page in pages for p in page), method)
        out = [PageText(index=i, label=str(n), text="\n\n".join(page))
               for i, (n, page) in enumerate(zip(self.numbers, pages)) if page]
        for i, p in enumerate(out):
            p.index = i
        return ExtractedDoc(pages=out, n_pages=len(out), method=method, label_source=method)


# -- Word ----------------------------------------------------------------------------------------------------------
_W_SKIP = {MC + "Fallback", W + "moveFrom", W + "del", W + "pPrChange", W + "rPrChange", W + "instrText",
           W + "delText", W + "commentReference"}


def _note_texts(root: ET.Element | None, tag: str) -> dict[str, str]:
    """Fuss- bzw. Endnoten nach ID (ohne die Trennlinien-Einträge, die Word mit negativen IDs bzw. Typ führt)."""
    out: dict[str, str] = {}
    if root is None:
        return out
    for note in root.findall(tag):
        if note.get(W + "type") in ("separator", "continuationSeparator", "continuationNotice"):
            continue
        parts = []
        for p in note.iter(W + "p"):
            parts.append("".join(t.text or "" for t in p.iter(W + "t")))
        out[note.get(W + "id", "")] = " ".join(x for x in parts if x.strip())
    return out


def extract_docx(path: Path, max_pages: int = 3000) -> ExtractedDoc:
    with zipfile.ZipFile(path) as z:
        doc = _read_xml(z, "word/document.xml")
        if doc is None:
            raise ValueError("Keine Word-Datei (word/document.xml fehlt)")
        footnotes = _note_texts(_read_xml(z, "word/footnotes.xml"), W + "footnote")
        endnote_texts = _note_texts(_read_xml(z, "word/endnotes.xml"), W + "endnote")
    body = doc.find(W + "body")
    if body is None:
        return ExtractedDoc(method="docx")
    paged = body.find(".//" + W + "lastRenderedPageBreak") is not None
    # Abschnitte: jedes sectPr beendet einen Abschnitt; pgNumType/@start setzt dessen Seitenzählung neu
    starts = []
    for sect in body.iter(W + "sectPr"):
        num = sect.find(W + "pgNumType")
        start = num.get(W + "start") if num is not None else None
        starts.append(int(start) if start and start.isdigit() else None)
    pages = _Pages(starts[0] if starts and starts[0] is not None else 1, max_pages)
    section = 0
    notes_seen = {"foot": 0, "end": 0}
    endnotes: list[str] = []

    def inline(el: ET.Element) -> None:
        for child in el:
            tag = child.tag
            if tag in _W_SKIP:
                continue
            if tag == W + "t":
                pages.text(child.text or "")
            elif tag in (W + "tab", W + "cr"):
                pages.text(" ")
            elif tag == W + "br":
                pages.text(" ")
            elif tag == W + "noBreakHyphen":
                pages.text("-")
            elif tag == W + "lastRenderedPageBreak":
                if paged:
                    pages.page_break()
            elif tag == W + "footnoteReference":
                notes_seen["foot"] += 1
                text = footnotes.get(child.get(W + "id", ""))
                if text:
                    pages.note(f"{notes_seen['foot']} {text}")
            elif tag == W + "endnoteReference":
                notes_seen["end"] += 1
                text = endnote_texts.get(child.get(W + "id", ""))
                if text:
                    endnotes.append(f"{notes_seen['end']} {_WS.sub(' ', text).strip()}")
            elif tag == W + "p":  # Absatz in einem Textfeld: wie Leerzeichen
                pages.text(" ")
                inline(child)
                pages.text(" ")
            else:
                inline(child)

    def paragraph(p: ET.Element, in_table: bool) -> None:
        nonlocal section
        inline(p)
        if in_table:
            pages.text(" ")
        else:
            pages.end_para()
        ppr = p.find(W + "pPr")
        if ppr is not None and ppr.find(W + "sectPr") is not None:  # Abschnittsende
            section += 1
            if section < len(starts) and starts[section] is not None:
                pages.restart = starts[section]

    def block(el: ET.Element, in_table: bool = False) -> None:
        for child in el:
            tag = child.tag
            if tag == W + "p":
                paragraph(child, in_table)
            elif tag == W + "tbl":
                for row in child.findall(W + "tr"):  # direkte Zeilen; verschachtelte Tabellen liest block(cell)
                    cells = row.findall(W + "tc")
                    for i, cell in enumerate(cells):
                        block(cell, in_table=True)
                        if i < len(cells) - 1:
                            pages.text(" | ")
                    if not in_table:
                        pages.end_para()
            elif tag in (W + "sdt", W + "sdtContent", W + "customXml", W + "ins", W + "smartTag"):
                block(child, in_table)
            elif tag in _W_SKIP or tag == W + "sectPr":
                continue

    block(body)
    return pages.document("docx", paged, endnotes)


# -- OpenDocument ----------------------------------------------------------------------------------------------------
def _odt_break_styles(*roots: ET.Element | None) -> dict[str, tuple[bool, bool, int | None]]:
    """Absatzformate mit hartem Seitenumbruch: Name → (davor, danach, neue Seitenzahl). Vererbung über
    style:parent-style-name; ein Absatzformat mit Seitenvorlage (master-page-name) beginnt eine neue Seite."""
    raw: dict[str, tuple[str | None, bool, bool, int | None]] = {}
    for root in roots:
        if root is None:
            continue
        for st in root.iter(STYLE + "style"):
            if st.get(STYLE + "family") != "paragraph":
                continue
            props = st.find(STYLE + "paragraph-properties")
            before = after = False
            number = None
            if props is not None:
                before = props.get(FO + "break-before") == "page"
                after = props.get(FO + "break-after") == "page"
                num = props.get(STYLE + "page-number") or ""
                number = int(num) if num.isdigit() else None
            if st.get(STYLE + "master-page-name"):
                before = True
            raw[st.get(STYLE + "name", "")] = (st.get(STYLE + "parent-style-name"), before, after, number)

    def resolve(name: str, depth: int = 0) -> tuple[bool, bool, int | None]:
        parent, before, after, number = raw.get(name, (None, False, False, None))
        if parent and depth < 10:
            pb, pa, pn = resolve(parent, depth + 1)
            return before or pb, after or pa, number if number is not None else pn
        return before, after, number

    return {name: resolve(name) for name in raw}


def _odt_rows(table: ET.Element):
    """Zeilen einer Tabelle, auch in Kopfzeilen- und Zeilengruppen – ohne die verschachtelter Tabellen."""
    for child in table:
        if child.tag == TABLE + "table-row":
            yield child
        elif child.tag in (TABLE + "table-header-rows", TABLE + "table-rows", TABLE + "table-row-group"):
            yield from _odt_rows(child)


_ODT_SKIP_BLOCKS = {TEXT + "table-of-content", TEXT + "alphabetical-index", TEXT + "illustration-index",
                    TEXT + "table-index", TEXT + "object-index", TEXT + "user-index", TEXT + "bibliography",
                    TEXT + "tracked-changes", OFFICE + "annotation", OFFICE + "forms", TEXT + "sequence-decls",
                    TEXT + "variable-decls", TEXT + "user-field-decls"}


def extract_odt(path: Path, max_pages: int = 3000) -> ExtractedDoc:
    with zipfile.ZipFile(path) as z:
        content = _read_xml(z, "content.xml")
        if content is None:
            raise ValueError("Keine OpenDocument-Datei (content.xml fehlt)")
        styles = _read_xml(z, "styles.xml")
    text_root = content.find(f"{OFFICE}body/{OFFICE}text")
    if text_root is None:
        return ExtractedDoc(method="odt")
    paged = text_root.find(".//" + TEXT + "soft-page-break") is not None
    breaks = _odt_break_styles(styles, content)
    first = next(text_root.iter(TEXT + "p"), None)
    first_number = breaks.get(first.get(TEXT + "style-name", ""), (False, False, None))[2] if first is not None else None
    pages = _Pages(first_number or 1, max_pages)
    started = False  # harte Umbrüche vor dem ersten Text zählen nicht
    endnotes: list[str] = []
    counter = {"foot": 0, "end": 0}

    def note_text(note: ET.Element) -> str:
        body = note.find(TEXT + "note-body")
        if body is None:
            return ""
        return " ".join("".join(p.itertext()) for p in body.iter() if p.tag in (TEXT + "p", TEXT + "h"))

    def inline(el: ET.Element) -> None:
        nonlocal started
        if el.text:
            pages.text(el.text)
            started = True
        for child in el:
            tag = child.tag
            if tag == TEXT + "s":
                pages.text(" " * int(child.get(TEXT + "c", "1") or 1))
            elif tag in (TEXT + "tab", TEXT + "line-break"):
                pages.text(" ")
            elif tag == TEXT + "soft-page-break":
                if paged:
                    pages.page_break()
            elif tag == TEXT + "note":
                kind = "end" if child.get(TEXT + "note-class") == "endnote" else "foot"
                counter[kind] += 1
                text = _WS.sub(" ", note_text(child)).strip()
                if text:
                    if kind == "end":
                        endnotes.append(f"{counter['end']} {text}")
                    else:
                        pages.note(f"{counter['foot']} {text}")
            elif tag in (OFFICE + "annotation", OFFICE + "annotation-end", TEXT + "note-citation"):
                pass
            else:
                inline(child)
            if child.tail:
                pages.text(child.tail)
                started = True

    def paragraph(p: ET.Element, in_table: bool) -> None:
        before, after, number = breaks.get(p.get(TEXT + "style-name", ""), (False, False, None))
        if before and started and paged and not in_table:
            if number is not None:
                pages.restart = number
            pages.page_break()
        inline(p)
        if in_table:
            pages.text(" ")
        else:
            pages.end_para()
        if after and paged and not in_table:
            pages.page_break()

    def block(el: ET.Element, in_table: bool = False) -> None:
        for child in el:
            tag = child.tag
            if tag in _ODT_SKIP_BLOCKS:
                continue
            if tag in (TEXT + "p", TEXT + "h"):
                paragraph(child, in_table)
            elif tag == TEXT + "soft-page-break":
                if paged:
                    pages.page_break()
            elif tag == TABLE + "table":
                for row in _odt_rows(child):
                    cells = row.findall(TABLE + "table-cell")
                    for i, cell in enumerate(cells):
                        block(cell, in_table=True)
                        if i < len(cells) - 1:
                            pages.text(" | ")
                    if not in_table:
                        pages.end_para()
            elif tag in (TEXT + "list", TEXT + "list-item", TEXT + "list-header", TEXT + "section",
                         TABLE + "table-cell"):
                block(child, in_table)

    block(text_root)
    return pages.document("odt", paged, endnotes)
