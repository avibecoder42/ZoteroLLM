"""Textextraktion mit Seitenzahlen (PDF, EPUB, HTML) über PyMuPDF."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import pymupdf

from zotivity.extract.pagenumbers import clean_pdf_label, detect_page_labels, margin_candidates

log = logging.getLogger(__name__)

pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

_TEXT_FLAGS = (
    pymupdf.TEXT_DEHYPHENATE
    | pymupdf.TEXT_PRESERVE_LIGATURES
    | pymupdf.TEXT_MEDIABOX_CLIP
)


@dataclass
class PageText:
    index: int  # 0-basiert (physische Seite)
    label: str  # gedruckte Seitenzahl (Kopf-/Fusszeile), "" = ohne Seitenzahl („o. S.“)
    text: str  # Absätze durch Leerzeile getrennt
    has_images: bool = False


@dataclass
class ExtractedDoc:
    pages: list[PageText] = field(default_factory=list)
    n_pages: int = 0
    method: str = "pymupdf"
    needs_ocr: bool = False
    warnings: list[str] = field(default_factory=list)
    label_source: str = ""  # woher die Seitenzahlen stammen (kopfzeile, pdf, zotero) – "" = keine erkannt

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)


_WS = re.compile(r"[ \t   ]+")
_SOFT_HYPHEN = "­"
_DIGITS = re.compile(r"\d+")
_LEADERS = re.compile(r"(?:\s?[.·…_]){4,}\s?")  # Punktlinien in Inhaltsverzeichnissen


def _clean_block(text: str) -> str:
    text = text.replace(_SOFT_HYPHEN, "")
    # Zeilenumbrüche innerhalb eines Blocks sind Satzspiegel, keine Absätze
    lines = [ln.strip() for ln in text.splitlines()]
    out = ""
    for ln in lines:
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower() and not out.endswith(" -"):
            out = out[:-1] + ln  # Silbentrennung, die PyMuPDF nicht erkannt hat
        else:
            out = f"{out} {ln}" if out else ln
    out = _LEADERS.sub(" … ", out)
    return _WS.sub(" ", out).strip()


def _norm_line(line: str) -> str:
    return _DIGITS.sub("#", line.strip().lower())


def _strip_running_heads(pages: list[list[str]]) -> list[list[str]]:
    """Entfernt wiederkehrende Kopf-/Fusszeilen (Zeitschriftentitel, Seitenzahlen)."""
    if len(pages) < 4:
        return pages
    counter: Counter[str] = Counter()
    for blocks in pages:
        edge = blocks[:2] + blocks[-2:]
        counter.update({_norm_line(b) for b in edge if len(b) < 160})
    threshold = max(3, int(len(pages) * 0.4))
    repeated = {k for k, v in counter.items() if v >= threshold}
    repeated.add("#")  # reine Seitenzahlen
    out = []
    for blocks in pages:
        keep = list(blocks)
        for pos in (0, 1, -1, -2):
            if not keep:
                break
            idx = pos if pos >= 0 else len(keep) + pos
            if 0 <= idx < len(keep) and _norm_line(keep[idx]) in repeated:
                keep[idx] = ""
        out.append([b for b in keep if b])
    return out


def _page_blocks(page: pymupdf.Page, textpage=None) -> tuple[list[str], bool, list[tuple[str, int]]]:
    """Textblöcke, ob die Seite Bilder hat, und Seitenzahl-Kandidaten aus Kopf-/Fusszeilen."""
    blocks = page.get_text("blocks", flags=_TEXT_FLAGS, textpage=textpage) if textpage else \
        page.get_text("blocks", flags=_TEXT_FLAGS)
    texts: list[str] = []
    positioned: list[tuple[float, float, float, float, str]] = []
    has_images = False
    for b in blocks:
        if b[6] == 1:
            has_images = True
            continue
        t = _clean_block(b[4])
        if t:
            texts.append(t)
            positioned.append((b[0], b[1], b[2], b[3], t))
    if not has_images and textpage is None:
        try:
            has_images = bool(page.get_images(full=False))
        except Exception:  # noqa: BLE001
            pass
    return texts, has_images, margin_candidates(positioned, page.rect.height)


def _ocr_page(page: pymupdf.Page, languages: str) -> tuple[list[str], list[tuple[str, int]]]:
    tp = page.get_textpage_ocr(language=languages, dpi=200, full=True)
    texts, _, cands = _page_blocks(page, textpage=tp)
    return texts, cands


def extract_with_pymupdf(
    path: Path,
    *,
    max_pages: int = 3000,
    min_chars_per_page: int = 40,
    ocr: bool = False,
    ocr_languages: str = "deu+eng",
    filetype: str | None = None,
    page_range: tuple[int, int] | None = None,
) -> ExtractedDoc:
    """page_range: Seitenspanne laut Zotero („Seiten“), zur Gegenprobe der erkannten Seitenzahlen."""
    doc = pymupdf.open(str(path), filetype=filetype) if filetype else pymupdf.open(str(path))
    result = ExtractedDoc(n_pages=doc.page_count)
    try:
        if doc.needs_pass:
            result.warnings.append("Passwortgeschütztes Dokument")
            return result
        n = min(doc.page_count, max_pages)
        if doc.page_count > max_pages:
            result.warnings.append(f"Nur die ersten {max_pages} von {doc.page_count} Seiten indexiert")
        raw: list[list[str]] = []
        cands: list[list[tuple[str, int]]] = []
        pdf_labels: list[str] = []
        images: list[bool] = []
        for i in range(n):
            page = doc.load_page(i)
            blocks, has_img, page_cands = _page_blocks(page)
            raw.append(blocks)
            cands.append(page_cands)
            images.append(has_img)
            try:
                pdf_labels.append(clean_pdf_label(page.get_label()))
            except Exception:  # noqa: BLE001
                pdf_labels.append("")
        total = sum(len(" ".join(b)) for b in raw)
        if n and total / n < min_chars_per_page:
            result.needs_ocr = True
            if ocr:
                try:
                    ocr_pages = [_ocr_page(doc.load_page(i), ocr_languages) for i in range(n)]
                    raw = [p[0] for p in ocr_pages]
                    cands = [p[1] for p in ocr_pages]
                    result.method = "ocr"
                    result.needs_ocr = False
                except Exception as e:  # noqa: BLE001  (Tesseract fehlt o. ä.)
                    result.warnings.append(f"Texterkennung nicht möglich: {e}")
        # Gedruckte Seitenzahlen bestimmen, bevor Kopf-/Fusszeilen aus dem Text entfernt werden
        labels, result.label_source = detect_page_labels(cands, pdf_labels if filetype is None else None, page_range)
        raw = _strip_running_heads(raw)
        for i in range(n):
            text = "\n\n".join(raw[i]).strip()
            result.pages.append(PageText(index=i, label=labels[i], text=text, has_images=images[i]))
    finally:
        doc.close()
    return result


class _HTMLText(HTMLParser):
    """Sichtbarer Text einer Webseite. Der Kopfbereich endet – wie im Browser – spätestens mit <body>: Gespeicherte
    Verlagsseiten (z. B. Wiley-Schnappschüsse aus Zotero) schliessen <head> nicht sauber, sonst ginge der ganze Text
    verloren. lenient=True überspringt nur Skripte, Stile und Grafiken (für Seiten mit ungeschlossenen nav/footer)."""
    _SKIP = {"script", "style", "noscript", "nav", "footer", "svg", "template"}
    _SKIP_LENIENT = {"script", "style", "svg", "template"}
    _BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "tr", "blockquote"}

    def __init__(self, lenient: bool = False):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_tags = self._SKIP_LENIENT if lenient else self._SKIP
        self._skip = 0
        self._head = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self._head = True
        elif tag == "body":
            self._head = False
        elif tag in self._skip_tags:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        # <svg/>, <br/> usw.: öffnet keinen Bereich
        if tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag == "head":
            self._head = False
        elif tag in self._skip_tags:
            if self._skip:
                self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self._skip and not self._head:
            self.parts.append(data)


def _html_text(html: str, lenient: bool) -> str:
    p = _HTMLText(lenient)
    p.feed(html)
    p.close()
    paras = [_WS.sub(" ", x).strip() for x in re.split(r"\n\s*\n", "".join(p.parts))]
    return "\n\n".join(x for x in paras if x)


def html_to_text(html: str) -> str:
    text = _html_text(html, lenient=False)
    if len(text) < 500:  # z. B. ein ungeschlossenes <nav> verschluckt den Rest: grosszügiger lesen
        loose = _html_text(html, lenient=True)
        if len(loose) > 2 * max(len(text), 1):
            return loose
    return text


def text_as_document(text: str, method: str) -> ExtractedDoc:
    """Fliesstext ohne Seiten (z. B. Zotero-Volltext) als Pseudoseiten von ~3000 Zeichen."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    pages: list[PageText] = []
    buf: list[str] = []
    size = 0
    for para in paras:
        buf.append(para)
        size += len(para)
        if size >= 3000:
            pages.append(PageText(index=len(pages), label="", text="\n\n".join(buf)))
            buf, size = [], 0
    if buf:
        pages.append(PageText(index=len(pages), label="", text="\n\n".join(buf)))
    return ExtractedDoc(pages=pages, n_pages=len(pages), method=method)


def extract_file(
    path: Path,
    content_type: str,
    *,
    max_pages: int = 3000,
    min_chars_per_page: int = 40,
    ocr: bool = False,
    ocr_languages: str = "deu+eng",
    page_range: tuple[int, int] | None = None,
) -> ExtractedDoc:
    ct = (content_type or "").lower()
    suffix = path.suffix.lower()
    if ct == "application/pdf" or suffix == ".pdf":
        return extract_with_pymupdf(
            path, max_pages=max_pages, min_chars_per_page=min_chars_per_page, ocr=ocr, ocr_languages=ocr_languages,
            page_range=page_range,
        )
    if ct == "application/epub+zip" or suffix == ".epub":
        doc = extract_with_pymupdf(path, max_pages=max_pages, min_chars_per_page=0, filetype="epub")
        for p in doc.pages:
            p.label = ""  # EPUB-Seiten sind umbrochen, keine echten Seitenzahlen
        doc.method = "epub"
        return doc
    if ct in ("text/html", "application/xhtml+xml") or suffix in (".html", ".htm", ".xhtml"):
        raw = path.read_bytes()
        html = raw.decode("utf-8", errors="replace")
        return text_as_document(html_to_text(html), "html")
    from zotivity.extract import office  # hier, weil office die Datenklassen aus diesem Modul verwendet

    if ct == office.DOCX_TYPE or suffix == ".docx":
        return office.extract_docx(path, max_pages=max_pages)
    if ct == office.ODT_TYPE or suffix == ".odt":
        return office.extract_odt(path, max_pages=max_pages)
    if ct.startswith("text/") or suffix in (".txt", ".md"):
        return text_as_document(path.read_text(encoding="utf-8", errors="replace"), "text")
    raise ValueError(f"Nicht unterstützter Dateityp: {content_type or suffix}")


def render_page_png(path: Path, page_index: int, zoom: float = 1.6) -> bytes:
    """Seite als PNG (für Bildanfragen an multimodale LLMs)."""
    with pymupdf.open(str(path)) as doc:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
