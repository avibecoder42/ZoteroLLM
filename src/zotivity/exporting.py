"""Export von KI-Ausgaben (Antworten, Textstellen, Forschungsstand) als Text, HTML, Markdown, Word und LaTeX.

Word (.docx): Belege und Literaturverzeichnis sind Zotero-Felder (ADDIN ZOTERO_ITEM CSL_CITATION / ZOTERO_BIBL)
mit den Dokumenteinstellungen von Zotero – das Zotero-Word-Plugin erkennt sie, „Refresh“ formatiert sie im
gewählten Zitierstil, und Belege lassen sich wie selbst eingefügte bearbeiten.
LaTeX (.tex): \\parencite-Belege und die BibTeX-Daten aus Zotero in einer filecontents-Umgebung – eine Datei,
direkt mit biblatex/biber übersetzbar; die .bib lässt sich auch in Zotero importieren.

Zitationsdaten (CSL-JSON, Literaturverzeichnis, BibTeX) kommen aus der lokalen Zotero-API; ist Zotero
geschlossen, werden sie aus den gespeicherten Metadaten erzeugt.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import re
import secrets
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as xesc

from zotivity.engine import Engine
from zotivity.index.store import strip_bidi
from zotivity.rag.markdown import MATH, is_math, latex_to_text

log = logging.getLogger(__name__)

CSL_SCHEMA = "https://github.com/citation-style-language/schema/raw/master/csl-citation.json"
LOCALES = {"de": "de-DE", "en": "en-US", "fr": "fr-FR", "it": "it-IT", "es": "es-ES"}
PAGE = {"de": "S.", "en": "p.", "fr": "p.", "it": "p.", "es": "p."}
BIB_HEADING = {"de": "Literatur", "en": "References", "fr": "Bibliographie", "it": "Bibliografia", "es": "Referencias"}

# ------------------------------------------------------------------------------------------- Modell


@dataclass
class CiteItem:
    lib: str
    key: str
    locator: str = ""
    suppress_author: bool = False  # Name steht schon im Satz („Shin et al. (2021)“)


@dataclass
class Document:
    """Text in Markdown; Belege als Platzhalter \\x00<n>\\x00 auf cites[n]."""
    title: str
    markdown: str
    cites: list[list[CiteItem]] = field(default_factory=list)
    appendix: str = ""  # Markdown ohne Belege (z. B. Methode der Literatursuche)
    language: str = "de"

    def add_cite(self, items: list[CiteItem]) -> str:
        self.cites.append(items)
        return f"\x00{len(self.cites) - 1}\x00"

    def items(self) -> list[tuple[str, str]]:
        seen: list[tuple[str, str]] = []
        for group in self.cites:
            for c in group:
                if (c.lib, c.key) not in seen:
                    seen.append((c.lib, c.key))
        return seen


_CITE_N = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\]")


def _numbers(inner: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"[,;]", inner):
        r = [x.strip() for x in re.split(r"[–-]", part) if x.strip()]
        if len(r) == 2 and r[0].isdigit() and r[1].isdigit() and 0 <= int(r[1]) - int(r[0]) < 20:
            out.extend(range(int(r[0]), int(r[1]) + 1))
        elif r and r[0].isdigit():
            out.append(int(r[0]))
    return out


def _source_page(source: dict) -> str:
    """Seitenangabe einer Textstelle: gedruckte Seite; Textstellen aus Quellen ohne Seitenzahlen „o. S.“
    (Abstracts aus den Zotero-Daten haben keine Seite)."""
    from zotivity.rag.review import NO_PAGE

    return source.get("page_label") or (NO_PAGE if source.get("kind") == "text" else "")


def answer_document(engine: Engine, message_id: int, language: str) -> Document:
    """Antwort aus einem Chat: [n] → Beleg auf Textstelle n (Eintrag + Seite)."""
    msg, question = _message(engine, message_id)
    sources = {s["n"]: s for s in msg.get("sources") or []}
    doc = Document(title=question or "Zotivity", markdown="", language=language)

    def repl(m: re.Match) -> str:
        items, seen = [], set()
        for n in _numbers(m.group(1)):
            if n in sources and n not in seen:
                seen.add(n)
                items.append(CiteItem(sources[n]["lib"], sources[n]["item_key"], _source_page(sources[n])))
        return doc.add_cite(items) if items else m.group(0)

    # Nebeneinanderstehende Belege „[1][2]“ werden ein gemeinsamer Beleg „[1, 2]“
    text = msg.get("content") or ""
    while True:
        merged = re.sub(r"\[(\d[\d,;\s–-]*)\]\s*\[(?=\d)", r"[\1, ", text)
        if merged == text:
            break
        text = merged
    doc.markdown = _CITE_N.sub(repl, text)
    return doc


def sources_document(engine: Engine, message_id: int, language: str) -> Document:
    """Textstellen einer Antwort: je Stelle Kopf, Zitat und Beleg mit Seite."""
    msg, question = _message(engine, message_id)
    doc = Document(title=question or "Textstellen", markdown="", language=language)
    parts = []
    for s in msg.get("sources") or []:
        cite = doc.add_cite([CiteItem(s["lib"], s["item_key"], _source_page(s))])
        head = f"### [{s['n']}] {s.get('citation', '')} – {s.get('title', '')}"
        text = " ".join((s.get("text") or "").split())
        parts.append(f"{head}\n\n> „{text}“ {cite}")
    doc.markdown = "\n\n".join(parts)
    return doc


def review_document(engine: Engine, review_id: int, language: str) -> Document:
    from zotivity.rag.review import ReviewService, named_before, parse_citation

    svc = ReviewService(engine)
    review = engine.store.get_review(review_id)
    if not review:
        raise KeyError(review_id)
    state = review["state"]
    docs = {d["item_key"]: d for d in engine.store.review_docs(review_id)}
    data = svc._items((d["lib"], d["item_key"]) for d in docs.values())
    doc = Document(title=(state.get("outline") or {}).get("title") or review["title"], markdown="",
                   language=state.get("language") or language)

    def repl(m: re.Match) -> str:
        items = [CiteItem(docs[k]["lib"], k, page) for k, page in parse_citation(m.group(1)) if k in docs]
        # „Shin et al. [@KEY]“: der Name steht schon im Satz – Zotero nennt im Beleg nur Jahr und Seite
        if items and named_before(body[:m.start()], data.get((items[0].lib, items[0].key)) or {}):
            items[0].suppress_author = True
        return doc.add_cite(items) if items else m.group(0)

    body = "\n\n".join(s["text"] for s in state.get("sections", []))
    doc.markdown = re.sub(r"\[(@[^\]]+)\]", repl, body)
    doc.appendix = svc.method_appendix(review)
    return doc


def _message(engine: Engine, message_id: int) -> tuple[dict, str]:
    row = engine.store.con.execute("SELECT * FROM chat_messages WHERE id=?", (message_id,)).fetchone()
    if not row:
        raise KeyError(message_id)
    msg = dict(row)
    msg["sources"] = json.loads(msg["sources"] or "[]")
    prev = engine.store.con.execute(
        "SELECT content FROM chat_messages WHERE chat_id=? AND id<? AND role='user' ORDER BY id DESC LIMIT 1",
        (msg["chat_id"], message_id)).fetchone()
    return msg, (prev[0] if prev else "")


# ------------------------------------------------------------------------------------------- Zitationsdaten
class Citations:
    """CSL-JSON, Kurzbelege, Literaturverzeichnis, BibTeX und Zotero-URIs für die Einträge eines Dokuments."""

    def __init__(self, engine: Engine, keys: list[tuple[str, str]], style: str, language: str,
                 no_page: str | None = None):
        from zotivity.zotero.styles import (analyze_locator, analyze_names, installed_styles, normalize_style_id,
                                             style_xml, zotero_data_dir)

        self.engine = engine
        self.keys = keys
        self.style = normalize_style_id(style)
        self.language = language if language in LOCALES else "de"
        # Wie der Stil Seiten setzt – bestimmt, wie „o. S.“ in den Zotero-Beleg kommt (Seitenangabe oder Suffix)
        data_dir = zotero_data_dir(engine.store)
        xml = style_xml(self.style, data_dir)
        self.loc = analyze_locator(xml)
        # … und die Namen (FHNW „Gong/Li“, APA „Gong & Li“, ab drei Namen „et al.“)
        self.names = analyze_names(xml, self.language)
        info = next((s for s in installed_styles(data_dir) if s.id == self.style), None)
        self.style_format = info.format if info else "author-date"
        self.style_title = info.title if info else self.style.rstrip("/").rsplit("/", 1)[-1]
        self.no_page = engine.settings.citation_no_page if no_page is None else no_page
        self.items = engine.store.items(keys)
        gone = [k for k in keys if k not in self.items]
        if gone:  # in Zotero gelöscht: gespeicherte Kurzangaben statt „o. A.“
            self.items.update(engine.store.removed_items(gone))
        self.csl: dict[tuple[str, str], dict] = {}
        self.bib_html: list[str] = []
        self.bibtex: dict[tuple[str, str], tuple[str, str]] = {}  # → (citekey, eintrag)
        self.uris: dict[tuple[str, str], str] = {}
        self.from_zotero = False
        self._load()

    # -- aus Zotero --------------------------------------------------------------------------
    def _load(self) -> None:
        zot = self.engine.zotero()
        try:
            online = zot.is_available()
        except Exception:  # noqa: BLE001
            online = False
        by_lib: dict[str, list[str]] = {}
        for lib, key in self.keys:
            by_lib.setdefault(lib, []).append(key)
        if online:
            try:
                self._load_from_zotero(zot, by_lib)
                self.from_zotero = True
            except Exception as e:  # noqa: BLE001 - Rückfall auf gespeicherte Metadaten
                log.info("Zitationsdaten aus Zotero nicht verfügbar: %s", e)
            # Zotero sortiert je Bibliothek: Einträge aus mehreren Bibliotheken (eigene und Gruppen) zusammen ordnen
            if len(by_lib) > 1 and self.bib_html and self.style_format != "numeric":
                self.bib_html.sort(key=lambda e: html.unescape(re.sub(r"<[^>]+>", "", e)).strip().casefold())
        for k in self.keys:
            self.csl.setdefault(k, self._csl_fallback(k))
            self.uris.setdefault(k, self._uri_fallback(k))
            if k not in self.bibtex:
                self.bibtex[k] = self._bibtex_fallback(k)
        if not self.bib_html:
            self.bib_html = [html.escape(self._bib_fallback(k)) for k in self._sorted_keys()]
        self._unique_bibtex_keys()

    def _load_from_zotero(self, zot, by_lib: dict[str, list[str]]) -> None:
        locale = LOCALES[self.language]
        for lib, keys in by_lib.items():
            for i in range(0, len(keys), 50):
                batch = keys[i:i + 50]
                r = zot._request("GET", f"/api/{lib}/items", params={"itemKey": ",".join(batch), "format": "csljson"})
                if r.status_code == 200:
                    data = r.json()
                    for entry in data.get("items", data) if isinstance(data, dict) else data:
                        key = str(entry.get("id", "")).split("/")[-1]
                        if key in batch:
                            self.csl[(lib, key)] = entry
                r = zot._request("GET", f"/api/{lib}/items", params={"itemKey": ",".join(batch), "format": "bib",
                                                                      "style": self.style, "locale": locale})
                if r.status_code == 200:
                    self.bib_html += re.findall(r'<div class="csl-entry"[^>]*>(.*?)</div>', r.text, re.S)
            for key in keys:
                r = zot._request("GET", f"/api/{lib}/items/{key}", params={"format": "bibtex"})
                if r.status_code == 200 and r.text.strip().startswith("@"):
                    m = re.match(r"\s*@\w+\s*\{\s*([^,\s]+)", r.text)
                    if m:
                        self.bibtex[(lib, key)] = (m.group(1), r.text.strip())
            if lib.startswith("users/") and keys:
                # Synchronisierte eigene Bibliothek: URI mit der Zotero-Benutzer-ID
                r = zot._request("GET", f"/api/{lib}/items/{keys[0]}", params={"format": "json"})
                uid = ((r.json() or {}).get("library") or {}).get("id") if r.status_code == 200 else None
                if uid:
                    for key in keys:
                        self.uris[(lib, key)] = f"http://zotero.org/users/{uid}/items/{key}"
        # Genaue URIs (auch für nicht synchronisierte Bibliotheken) liefert das Zotivity-Plugin
        for ref, uri in zot.item_uris([f"{lib}:{k}" for lib, k in self.keys]).items():
            lib, _, key = ref.partition(":")
            self.uris[(lib, key)] = uri

    # -- Rückfall: aus gespeicherten Metadaten ------------------------------------------------
    _CSL_TYPES = {"journalArticle": "article-journal", "book": "book", "bookSection": "chapter", "thesis": "thesis",
                  "report": "report", "webpage": "webpage", "conferencePaper": "paper-conference",
                  "magazineArticle": "article-magazine", "newspaperArticle": "article-newspaper", "document": "document",
                  "manuscript": "manuscript", "presentation": "speech", "blogPost": "post-weblog", "preprint": "article",
                  "encyclopediaArticle": "entry-encyclopedia", "dictionaryEntry": "entry-dictionary", "dataset": "dataset"}

    def _csl_fallback(self, k: tuple[str, str]) -> dict:
        it = self.items.get(k) or {}
        d = it.get("data") or {}
        names = []
        for c in it.get("creators") or []:
            if c.get("name"):
                names.append({"literal": c["name"]})
            else:
                names.append({"family": c.get("lastName", ""), "given": c.get("firstName", "")})
        csl = {"id": f"{k[0]}/{k[1]}", "type": self._CSL_TYPES.get(it.get("item_type") or "", "document"),
               "title": it.get("title") or "", "author": names}
        if it.get("year"):
            csl["issued"] = {"date-parts": [[int(it["year"])]]}
        if it.get("publication"):
            csl["container-title"] = it["publication"]
        for src, dst in (("volume", "volume"), ("issue", "issue"), ("pages", "page"), ("publisher", "publisher"),
                         ("place", "publisher-place"), ("DOI", "DOI"), ("url", "URL"), ("ISBN", "ISBN")):
            if d.get(src):
                csl[dst] = d[src]
        return csl

    @staticmethod
    def _uri_fallback(k: tuple[str, str]) -> str:
        lib, key = k
        if lib.startswith("groups/"):
            return f"http://zotero.org/{lib}/items/{key}"
        return f"http://zotero.org/users/local/zotivity/items/{key}"

    def _bib_fallback(self, k: tuple[str, str]) -> str:
        from zotivity.rag.sources import author_year

        it = self.items.get(k) or {}
        who_year = author_year(it)
        title = (it.get("title") or "").strip()
        parts = [f"{who_year}.", title + ("." if title and not title.endswith((".", "?", "!")) else "")]
        if it.get("publication"):
            parts.append(f"{it['publication']}.")
        if it.get("doi"):
            parts.append(f"https://doi.org/{it['doi']}")
        return " ".join(p for p in parts if p).replace("..", ".")

    def _bibtex_fallback(self, k: tuple[str, str]) -> tuple[str, str]:
        it = self.items.get(k) or {}
        d = it.get("data") or {}
        first = (it.get("creators") or [{}])[0]
        base = _ascii(first.get("lastName") or first.get("name") or "o") or "o"
        word = _ascii((re.findall(r"\w{4,}", it.get("title") or "") or ["text"])[0]) or "text"
        key = f"{base}_{word}_{it.get('year') or 'oj'}"
        kind = {"journalArticle": "article", "book": "book", "bookSection": "incollection", "thesis": "phdthesis",
                "report": "techreport", "conferencePaper": "inproceedings"}.get(it.get("item_type") or "", "misc")
        authors = " and ".join(f"{c.get('lastName', '')}, {c.get('firstName', '')}".strip(", ") if not c.get("name")
                               else "{" + c["name"] + "}" for c in it.get("creators") or [])
        fields = {"author": authors, "title": it.get("title"), "year": it.get("year"),
                  "journal" if kind == "article" else "booktitle" if kind in ("incollection", "inproceedings")
                  else "publisher": it.get("publication"),
                  "volume": d.get("volume"), "number": d.get("issue"), "pages": d.get("pages"), "doi": it.get("doi"),
                  "url": it.get("url")}
        body = ",\n".join(f"\t{name} = {{{_tex_escape_bib(str(v))}}}" for name, v in fields.items() if v)
        return key, f"@{kind}{{{key},\n{body}\n}}"

    def _unique_bibtex_keys(self) -> None:
        seen: dict[str, int] = {}
        for k in self.keys:
            key, entry = self.bibtex[k]
            if key in seen:
                seen[key] += 1
                new = f"{key}{chr(96 + seen[key])}"
                entry = entry.replace(key, new, 1)
                self.bibtex[k] = (new, entry)
            else:
                seen[key] = 1

    def _sorted_keys(self) -> list[tuple[str, str]]:
        from zotivity.rag.sources import author_year

        return sorted(self.keys, key=lambda k: author_year(self.items.get(k) or {}).casefold())

    # -- Ausgabe ---------------------------------------------------------------------------------
    def _is_no_page(self, c: CiteItem) -> bool:
        from zotivity.rag.review import NO_PAGE

        return c.locator == NO_PAGE

    def short(self, group: list[CiteItem]) -> str:
        """Kurzbeleg im Text nach dem Muster des Stils, z. B. (Müller, 2024, S. 12; Meier, 2021) oder
        (Müller 2024: 12). In Word formatiert Zotero ihn beim Aktualisieren ohnehin genau im Stil."""
        from zotivity.rag.sources import author_year

        loc = self.loc
        out = []
        for c in group:
            it = self.items.get((c.lib, c.key)) or {}
            styled = self.names.format(_family_names(it), self.language) if self.names.found else ""
            if c.suppress_author:
                label = str(it.get("year") or ("o. J." if self.language == "de" else "n.d."))
            elif styled:
                year = it.get("year") or ("o. J." if self.language == "de" else "n.d.")
                label = f"{styled}{loc.author_date}{year}"
            else:
                ay = author_year(it)
                who, _, year = ay.rpartition(" ")
                label = f"{who}{loc.author_date}{year}" if who else ay
            if self._is_no_page(c):
                label += f"{loc.delimiter}{self.no_page}" if self.no_page else ""
            elif c.locator:
                label += f"{loc.delimiter}{PAGE[self.language] + ' ' if loc.label else ''}{c.locator}"
            out.append(label)
        prefix, suffix = (loc.prefix, loc.suffix) if loc.found and self.style_format != "numeric" else ("(", ")")
        return prefix + "; ".join(out) + suffix

    def biblatex_style(self) -> str:
        """biblatex kann Zotero-Stile nicht nachbilden – passende Grundform nach Art des Stils."""
        if self.style.rstrip("/").endswith("/apa"):
            return "apa"
        return "numeric" if self.style_format == "numeric" else "authoryear"

    def item_id(self, k: tuple[str, str]) -> int:
        return int(hashlib.md5(f"{k[0]}/{k[1]}".encode()).hexdigest()[:7], 16)  # noqa: S324

    def citation_json(self, group: list[CiteItem]) -> str:
        items = []
        for c in group:
            k = (c.lib, c.key)
            data = dict(self.csl.get(k) or {})
            data["id"] = self.item_id(k)
            entry = {"id": self.item_id(k), "uris": [self.uris[k]], "itemData": data}
            if self._is_no_page(c):
                # Ohne Seitenzahl: je nach Stil als Seitenangabe (Stil setzt das Trennzeichen) oder als Suffix
                if self.no_page and self.loc.no_page_mode == "locator":
                    entry.update(locator=self.no_page, label="page")
                elif self.no_page:
                    entry["suffix"] = self.loc.suffix_for(self.no_page)
            elif c.locator:
                entry.update(locator=c.locator, label="page")
            if c.suppress_author:
                entry["suppress-author"] = True
            items.append(entry)
        formatted = self.short(group)
        return json.dumps({"citationID": secrets.token_hex(5),
                           "properties": {"formattedCitation": formatted, "plainCitation": formatted, "noteIndex": 0},
                           "citationItems": items, "schema": CSL_SCHEMA}, ensure_ascii=False)

    def bibliography_entries(self) -> list[list[tuple[str, dict]]]:
        """Einträge als Läufe (Text, Format) – kursiv aus <i>…</i> des Zotero-Literaturverzeichnisses."""
        out = []
        for entry in self.bib_html:
            runs: list[tuple[str, dict]] = []
            for part in re.split(r"(<i>.*?</i>)", entry, flags=re.S):
                if not part:
                    continue
                italic = part.startswith("<i>")
                text = html.unescape(re.sub(r"<[^>]+>", "", part))
                text = strip_bidi(re.sub(r"\s+", " ", text))
                if text:
                    runs.append((text, {"italic": italic}))
            if runs:
                runs[0] = (runs[0][0].lstrip(), runs[0][1])
                out.append(runs)
        return out

    def bibliography_text(self) -> list[str]:
        return ["".join(t for t, _ in runs).strip() for runs in self.bibliography_entries()]


def _family_names(item: dict) -> list[str]:
    """Nachnamen für den Kurzbeleg: Autorinnen und Autoren, sonst (wie cs:substitute) Herausgebende, sonst alle."""
    creators = item.get("creators") or []
    for role in ("author", "editor", None):
        chosen = [c for c in creators if role is None or (c.get("creatorType") or "author") == role]
        if chosen:
            return [strip_bidi(c.get("lastName") or c.get("name") or "") for c in chosen]
    return []


def _ascii(s: str) -> str:
    """Für BibTeX-Schlüssel: „Müller“ → „mueller“."""
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s)


def _tex_escape_bib(s: str) -> str:
    return s.replace("{", "").replace("}", "")


# ------------------------------------------------------------------------------------------- Markdown → Blöcke
@dataclass
class Block:
    kind: str  # heading, para, item, quote
    text: str
    level: int = 0


def blocks(md: str) -> list[Block]:
    out: list[Block] = []
    para: list[str] = []

    def flush():
        if para:
            out.append(Block("para", " ".join(para)))
            para.clear()

    for raw in (md or "").replace("\r", "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            out.append(Block("heading", m.group(2).strip(), min(len(m.group(1)), 3)))
            continue
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush()
            out.append(Block("item", m.group(1)))
            continue
        if line.lstrip().startswith(">"):
            flush()
            out.append(Block("quote", line.lstrip()[1:].strip()))
            continue
        para.append(line.strip())
    flush()
    # Oberste Überschriftenebene des Texts wird Ebene 1 (unter dem Dokumenttitel)
    levels = [b.level for b in out if b.kind == "heading"]
    if levels:
        shift = min(levels) - 1
        for b in out:
            if b.kind == "heading":
                b.level = max(1, b.level - shift)
    return out


_INLINE = re.compile(r"\x00(\d+)\x00|\*\*(.+?)\*\*|(?<![*\w])\*(?!\s)(.+?)\*(?!\w)|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text: str) -> list[tuple]:
    """→ [("text", str, {bold, italic, code}), ("cite", n)]."""
    out: list[tuple] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(("text", text[pos:m.start()], {}))
        if m.group(1) is not None:
            out.append(("cite", int(m.group(1))))
        elif m.group(2) is not None:
            out.append(("text", m.group(2), {"bold": True}))
        elif m.group(3) is not None:
            out.append(("text", m.group(3), {"italic": True}))
        elif m.group(4) is not None:
            out.append(("text", m.group(4), {"code": True}))
        else:
            out.append(("text", m.group(5), {}))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:], {}))
    return out


# ------------------------------------------------------------------------------------------- Ausgabeformate
def to_text(doc: Document, cit: Citations) -> str:
    lines = [doc.title, ""]
    for b in blocks(doc.markdown):
        txt = "".join(p[1] if p[0] == "text" else cit.short(doc.cites[p[1]]) for p in inline(b.text))
        lines.append(("• " if b.kind == "item" else "") + txt)
        lines.append("")
    bib = cit.bibliography_text()
    if bib:
        lines += [BIB_HEADING[cit.language], ""] + bib
    if doc.appendix:
        lines += ["", re.sub(r"[#|]", "", doc.appendix)]
    return "\n".join(lines).strip() + "\n"


def to_markdown(doc: Document, cit: Citations) -> str:
    body = re.sub(r"\x00(\d+)\x00", lambda m: cit.short(doc.cites[int(m.group(1))]), doc.markdown)
    bib = "\n".join(f"- {e}" for e in cit.bibliography_text())
    out = f"# {doc.title}\n\n{body}\n"
    if bib:
        out += f"\n## {BIB_HEADING[cit.language]}\n\n{bib}\n"
    if doc.appendix:
        out += f"\n{doc.appendix}\n"
    return out


def to_html(doc: Document, cit: Citations) -> str:
    """Für „Formatiert kopieren“ (Einfügen in Word, Mail …)."""
    def runs(text: str) -> str:
        out = []
        for p in inline(text):
            if p[0] == "cite":
                out.append(html.escape(cit.short(doc.cites[p[1]])))
            else:
                s = html.escape(p[1])
                if p[2].get("bold"):
                    s = f"<b>{s}</b>"
                if p[2].get("italic"):
                    s = f"<i>{s}</i>"
                out.append(s)
        return "".join(out)

    parts = [f"<h1>{html.escape(doc.title)}</h1>"]
    in_list = False
    for b in blocks(doc.markdown):
        if b.kind == "item" and not in_list:
            parts.append("<ul>")
            in_list = True
        if b.kind != "item" and in_list:
            parts.append("</ul>")
            in_list = False
        tag = {"heading": f"h{b.level + 1}", "para": "p", "item": "li", "quote": "blockquote"}[b.kind]
        parts.append(f"<{tag}>{runs(b.text)}</{tag}>")
    if in_list:
        parts.append("</ul>")
    entries = cit.bibliography_entries()
    if entries:
        parts.append(f"<h2>{BIB_HEADING[cit.language]}</h2>")
        for e in entries:
            parts.append("<p>" + "".join(f"<i>{html.escape(t)}</i>" if f.get("italic") else html.escape(t)
                                         for t, f in e) + "</p>")
    return "\n".join(parts)


# -- LaTeX ------------------------------------------------------------------------------------
_TEX_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def tex_escape(s: str) -> str:
    return "".join(_TEX_SPECIAL.get(ch, ch) for ch in s)


def to_latex(doc: Document, cit: Citations) -> str:
    page = PAGE[cit.language]

    def note(c: CiteItem) -> str:
        """Nachsatz für biblatex: „S.~12“, ohne Seitenzahl „o.~S.“ (Kennzeichnung aus den Einstellungen)."""
        if cit._is_no_page(c):
            return tex_escape(cit.no_page).replace(". ", ".~")
        return f"{page}~{tex_escape(c.locator)}" if c.locator else ""

    def cite(group: list[CiteItem]) -> str:
        keys = [cit.bibtex[(c.lib, c.key)][0] for c in group]
        if len(group) == 1:
            n = note(group[0])
            cmd = r"\parencite*" if group[0].suppress_author else r"\parencite"  # * : nur Jahr, Name steht im Satz
            return rf"{cmd}[{n}]{{{keys[0]}}}" if n else rf"{cmd}{{{keys[0]}}}"
        parts = "".join(f"[{note(c)}]{{{k}}}" if note(c) else f"{{{k}}}" for c, k in zip(group, keys))
        return rf"\parencites{parts}"

    def runs(text: str) -> str:
        """Formeln ($\\beta = .35$) bleiben in LaTeX Formeln; der übrige Text wird maskiert."""
        out, pos = [], 0
        for m in MATH.finditer(text):
            if is_math(m.group(1)):
                out += [plain_runs(text[pos:m.start()]), f"${m.group(1)}$"]
                pos = m.end()
        return "".join(out) + plain_runs(text[pos:])

    def plain_runs(text: str) -> str:
        out = []
        for p in inline(text):
            if p[0] == "cite":
                out.append(cite(doc.cites[p[1]]))
            else:
                s = tex_escape(p[1])
                if p[2].get("bold"):
                    s = rf"\textbf{{{s}}}"
                if p[2].get("italic"):
                    s = rf"\emph{{{s}}}"
                if p[2].get("code"):
                    s = rf"\texttt{{{s}}}"
                out.append(s)
        return "".join(out)

    body: list[str] = []
    in_list = False
    for b in blocks(doc.markdown):
        if b.kind == "item" and not in_list:
            body.append(r"\begin{itemize}")
            in_list = True
        if b.kind != "item" and in_list:
            body.append(r"\end{itemize}")
            in_list = False
        if b.kind == "heading":
            cmd = {1: "section", 2: "subsection"}.get(b.level, "subsubsection")
            body.append(rf"\{cmd}*{{{runs(b.text)}}}")
        elif b.kind == "item":
            body.append(rf"  \item {runs(b.text)}")
        elif b.kind == "quote":
            body.append(rf"\begin{{quote}}{runs(b.text)}\end{{quote}}")
        else:
            body.append(runs(b.text) + "\n")
    if in_list:
        body.append(r"\end{itemize}")
    babel = {"de": "ngerman", "en": "english", "fr": "french", "it": "italian", "es": "spanish"}[cit.language]
    bib = "\n\n".join(cit.bibtex[k][1] for k in cit.keys)
    appendix = ""
    if doc.appendix:
        rows = [r for r in doc.appendix.splitlines() if r.startswith("| ") and "---" not in r][1:]
        items = "\n".join(rf"  \item {tex_escape(r.strip('| ').split(' | ')[0])}" for r in rows)
        intro = "\n".join(tex_escape(line[2:]) + r"\\" for line in doc.appendix.splitlines() if line.startswith("- "))
        appendix = (rf"\section*{{{tex_escape(doc.appendix.splitlines()[0].lstrip('# '))}}}" + "\n" + intro
                    + ("\n\\begin{itemize}\n" + items + "\n\\end{itemize}" if items else ""))
    return f"""% Erstellt mit Zotivity am {time.strftime('%d.%m.%Y')} – übersetzen mit pdflatex/lualatex und biber.
% Die Literaturdatenbank steht unten in filecontents und wird beim Übersetzen als literatur.bib geschrieben;
% sie lässt sich auch in Zotero importieren (Datei → Importieren).
\\begin{{filecontents*}}[overwrite]{{literatur.bib}}
{bib}
\\end{{filecontents*}}
\\documentclass[11pt,a4paper]{{article}}
\\usepackage[T1]{{fontenc}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[{babel}]{{babel}}
\\usepackage{{amsmath}}
\\usepackage{{csquotes}}
\\usepackage[style={cit.biblatex_style()},backend=biber]{{biblatex}}
\\addbibresource{{literatur.bib}}
\\usepackage[hidelinks]{{hyperref}}
\\title{{{tex_escape(doc.title)}}}
\\date{{}}
\\begin{{document}}
\\maketitle

{chr(10).join(body)}

\\printbibliography[title={{{BIB_HEADING[cit.language]}}}]
{appendix}
\\end{{document}}
"""


# -- Word -------------------------------------------------------------------------------------
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _run(text: str, fmt: dict | None = None) -> str:
    fmt = fmt or {}
    props = ""
    if fmt.get("bold"):
        props += "<w:b/>"
    if fmt.get("italic"):
        props += "<w:i/>"
    if fmt.get("code"):
        props += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{xesc(text)}</w:t></w:r>'


def _field(code: str, result_runs: str) -> str:
    """Feld mit Code (in Stücken, Word erlaubt lange Feldcodes in mehreren instrText) und sichtbarem Ergebnis."""
    pieces = "".join(f'<w:r><w:instrText xml:space="preserve">{xesc(code[i:i + 200])}</w:instrText></w:r>'
                     for i in range(0, len(code), 200))
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + pieces
            + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + result_runs
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _para(content: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{content}</w:p>"


def to_docx(doc: Document, cit: Citations) -> bytes:
    def runs(text: str) -> str:
        out = []
        for p in inline(text):
            if p[0] == "cite":
                group = doc.cites[p[1]]
                out.append(_field(f" ADDIN ZOTERO_ITEM CSL_CITATION {cit.citation_json(group)} ", _run(cit.short(group))))
            else:
                out.append(_run(p[1], p[2]))
        return "".join(out)

    body = [_para(_run(doc.title), "Title")]
    for b in blocks(doc.markdown):
        if b.kind == "heading":
            body.append(_para(runs(b.text), f"Heading{b.level}"))
        elif b.kind == "item":
            body.append(_para(_run("• ") + runs(b.text), "ListParagraph"))
        elif b.kind == "quote":
            body.append(_para(runs(b.text), "Quote"))
        else:
            body.append(_para(runs(b.text)))
    entries = cit.bibliography_entries()
    if entries:
        body.append(_para(_run(BIB_HEADING[cit.language]), "Heading1"))
        # Literaturverzeichnis als ein Zotero-Feld über alle Absätze
        code = ' ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY '
        pieces = "".join(f'<w:r><w:instrText xml:space="preserve">{xesc(code)}</w:instrText></w:r>')
        for i, e in enumerate(entries):
            content = "".join(_run(t, f) for t, f in e)
            if i == 0:
                content = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + pieces
                           + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + content)
            if i == len(entries) - 1:
                content += '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            body.append(_para(content, "Bibliography"))
    if doc.appendix:
        for b in blocks(doc.appendix):
            if b.text.startswith("|"):
                cells = [c.strip() for c in b.text.strip("|").split("|")]
                if set("".join(cells)) <= set("-: "):
                    continue
                body.append(_para(_run("  ·  ".join(cells))))
            elif b.kind == "heading":
                body.append(_para(_run(b.text), "Heading1"))
            else:
                body.append(_para(_run(("• " if b.kind == "item" else "") + b.text)))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {W}><w:body>'
                + "".join(body)
                + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1134" '
                  'w:left="1417" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>')
    style_id = xesc(cit.style, {'"': "&quot;"})
    prefs = (f'<data data-version="3" zotero-version="7.0"><session id="{secrets.token_hex(4).upper()}"/>'
             f'<style id="{style_id}" locale="{LOCALES[cit.language]}" hasBibliography="1" '
             f'bibliographyStyleHasBeenSet="1"/><prefs><pref name="fieldType" value="Field"/></prefs></data>')
    custom = "".join(
        f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="{i + 2}" name="ZOTERO_PREF_{i + 1}">'
        f"<vt:lpwstr>{xesc(prefs[j:j + 240])}</vt:lpwstr></property>"
        for i, j in enumerate(range(0, len(prefs), 240)))
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
            "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/>'
            "</Relationships>"),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"),
        "word/document.xml": document,
        "word/styles.xml": _STYLES_XML,
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{xesc(doc.title)}</dc:title><dc:creator>Zotivity</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</dcterms:created>'
            "</cp:coreProperties>"),
        "docProps/app.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>Zotivity</Application></Properties>"),
        "docProps/custom.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            f"{custom}</Properties>"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


_STYLES_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="de-CH"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="23"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:ind w:left="567" w:right="567"/></w:pPr><w:rPr><w:i/><w:color w:val="404040"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:after="60"/><w:ind w:left="567" w:hanging="283"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Bibliography"><w:name w:val="Bibliography"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:after="120"/><w:ind w:left="720" w:hanging="720"/></w:pPr></w:style>
</w:styles>"""


# ------------------------------------------------------------------------------------------- Einstieg
def source_reference(engine: Engine, lib: str, key: str, page_label: str = "", kind: str = "text") -> dict:
    """Beleg einer einzelnen Textstelle im eingestellten Zitierstil (für „Textstelle kopieren“): Kurzbeleg mit
    Seite (bzw. „o. S.“) und Eintrag des Literaturverzeichnisses – aus Zotero, sonst nachgebildet."""
    from zotivity.extract.pagenumbers import clean_pdf_label

    settings = engine.settings
    language = settings.output_language if settings.output_language not in ("", "auto") else settings.language
    cit = Citations(engine, [(lib, key)], settings.citation_style, language if language in LOCALES else "de")
    item = CiteItem(lib, key, _source_page({"page_label": clean_pdf_label(page_label), "kind": kind}))
    bib = cit.bibliography_text()
    return {"short": cit.short([item]), "reference": bib[0] if bib else "", "from_zotero": cit.from_zotero}


def build(engine: Engine, kind: str, item_id: int, fmt: str) -> tuple[str, bytes | str | dict, str]:
    """→ (Dateiname, Inhalt, Medientyp). fmt: text (→ {text, html}), md, tex, docx."""
    settings = engine.settings
    language = settings.output_language if settings.output_language not in ("", "auto") else settings.language
    if kind == "answer":
        doc = answer_document(engine, item_id, language)
    elif kind == "sources":
        doc = sources_document(engine, item_id, language)
    elif kind == "review":
        doc = review_document(engine, item_id, language)
    else:
        raise ValueError("Unbekannte Art")
    cit = Citations(engine, doc.items(), settings.citation_style, doc.language if doc.language in LOCALES else "de")
    name = re.sub(r'[\\/:*?"<>|\n\r]+', " ", doc.title)[:80].strip() or "export"
    if fmt != "tex":  # Formeln in LaTeX-Schreibweise ($\beta = .35$) als Text (β = .35); in LaTeX bleiben sie Formeln
        doc.markdown = latex_to_text(doc.markdown)
    if fmt == "text":
        return name, {"text": to_text(doc, cit), "html": to_html(doc, cit), "from_zotero": cit.from_zotero}, "application/json"
    if fmt == "md":
        return f"{name}.md", to_markdown(doc, cit), "text/markdown; charset=utf-8"
    if fmt == "tex":
        return f"{name}.tex", to_latex(doc, cit), "application/x-tex; charset=utf-8"
    if fmt == "docx":
        return f"{name}.docx", to_docx(doc, cit), \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    raise ValueError("Unbekanntes Format")


# ------------------------------------------------------------------------------------------- Auswahl aus der Suche
SELECTION_TITLE = {"de": "Literaturliste", "en": "Reference list", "fr": "Liste de références",
                   "it": "Elenco bibliografico", "es": "Lista de referencias"}
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _output_language(engine: Engine) -> str:
    settings = engine.settings
    language = settings.output_language if settings.output_language not in ("", "auto") else settings.language
    return language if language in LOCALES else "de"


def _ordered(engine: Engine, keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Nach Autor/in, Jahr und Titel – wie ein Literaturverzeichnis."""
    from zotivity.rag.sources import author_year

    items = engine.store.items(keys)
    return sorted(dict.fromkeys(keys), key=lambda k: (author_year(items.get(k) or {}).casefold(),
                                                      ((items.get(k) or {}).get("title") or "").casefold()))


def selection_citations(engine: Engine, keys: list[tuple[str, str]]) -> dict:
    """Literaturliste und Kurzbelege der Auswahl im eingestellten Zitierstil („Literaturnachweis kopieren“)."""
    keys = _ordered(engine, keys)
    cit = Citations(engine, keys, engine.settings.citation_style, _output_language(engine))
    entries = cit.bibliography_entries()
    text = "\n".join("".join(t for t, _ in e).strip() for e in entries)
    html_out = "\n".join("<p>" + "".join(f"<i>{html.escape(t)}</i>" if f.get("italic") else html.escape(t)
                                         for t, f in e) + "</p>" for e in entries)
    return {"bibliography": {"text": text, "html": html_out}, "short": cit.short([CiteItem(*k) for k in keys]),
            "shorts": [cit.short([CiteItem(*k)]) for k in keys], "style": cit.style, "style_title": cit.style_title,
            "from_zotero": cit.from_zotero, "count": len(keys)}


def selection_document(engine: Engine, keys: list[tuple[str, str]], language: str) -> Document:
    """Literaturliste als Dokument: je Eintrag ein Beleg mit Titel, danach das Literaturverzeichnis (in Word als
    Zotero-Felder – mit dem Zotero-Plugin im Stil änderbar und in eigene Texte übernehmbar)."""
    items = engine.store.items(keys)
    doc = Document(title=SELECTION_TITLE.get(language, SELECTION_TITLE["de"]), markdown="", language=language)
    lines = []
    for k in _ordered(engine, keys):
        title = " ".join(((items.get(k) or {}).get("title") or k[1]).split())
        lines.append(f"- {doc.add_cite([CiteItem(*k)])} – {title}")
    doc.markdown = "\n".join(lines)
    return doc


_RIS_TYPES = {"journalArticle": "JOUR", "book": "BOOK", "bookSection": "CHAP", "thesis": "THES", "report": "RPRT",
              "conferencePaper": "CPAPER", "webpage": "ELEC", "magazineArticle": "MGZN", "newspaperArticle": "NEWS",
              "preprint": "UNPB", "dataset": "DATA", "presentation": "SLIDE", "blogPost": "BLOG"}


def ris_fallback(item: dict) -> str:
    """RIS-Eintrag aus den gespeicherten Metadaten (wenn Zotero nicht erreichbar ist)."""
    d = item.get("data") or {}
    lines = [f"TY  - {_RIS_TYPES.get(item.get('item_type') or '', 'GEN')}"]
    for c in item.get("creators") or []:
        tag = "A2" if c.get("creatorType") == "editor" else "AU"
        name = c.get("name") or ", ".join(x for x in (c.get("lastName"), c.get("firstName")) if x)
        if name:
            lines.append(f"{tag}  - {strip_bidi(name)}")
    for tag, value in (("TI", item.get("title")), ("T2", item.get("publication")), ("PY", item.get("year")),
                       ("VL", d.get("volume")), ("IS", d.get("issue")), ("SP", d.get("pages")),
                       ("PB", d.get("publisher")), ("CY", d.get("place")), ("SN", d.get("ISBN") or d.get("ISSN")),
                       ("DO", item.get("doi")), ("UR", item.get("url")), ("AB", item.get("abstract"))):
        if value:
            lines.append(f"{tag}  - {' '.join(str(value).split())}")
    return "\n".join(lines + ["ER  - ", ""])


def selection_ris(engine: Engine, keys: list[tuple[str, str]]) -> str:
    """RIS der Auswahl: aus Zotero (vollständig), sonst aus den gespeicherten Metadaten."""
    keys = _ordered(engine, keys)
    out: dict[tuple[str, str], str] = {}
    zot = engine.zotero()
    try:
        online = zot.is_available()
    except Exception:  # noqa: BLE001
        online = False
    if online:
        by_lib: dict[str, list[str]] = {}
        for lib, key in keys:
            by_lib.setdefault(lib, []).append(key)
        for lib, ks in by_lib.items():
            for k in ks:  # je Eintrag: Zotero liefert RIS ohne Schlüssel, die Zuordnung bliebe sonst offen
                try:
                    r = zot._request("GET", f"/api/{lib}/items/{k}", params={"format": "ris"})
                except Exception:  # noqa: BLE001
                    break
                if r.status_code == 200 and "TY  -" in r.text:
                    out[(lib, k)] = r.text.strip() + "\n"
    items = engine.store.items(keys)
    return "\n".join(out.get(k) or ris_fallback(items.get(k) or {}) for k in keys)


def build_selection(engine: Engine, keys: list[tuple[str, str]], fmt: str) -> tuple[str, bytes | str, str]:
    """Auswahl aus der Suche speichern: bib (BibTeX), ris, docx (Zotero-Felder), md."""
    language = _output_language(engine)
    name = SELECTION_TITLE.get(language, SELECTION_TITLE["de"])
    if fmt == "ris":
        return f"{name}.ris", selection_ris(engine, keys), "application/x-research-info-systems; charset=utf-8"
    doc = selection_document(engine, keys, language)
    cit = Citations(engine, doc.items(), engine.settings.citation_style, language)
    if fmt == "bib":
        return f"{name}.bib", "\n\n".join(cit.bibtex[k][1] for k in cit.keys) + "\n", "application/x-bibtex; charset=utf-8"
    if fmt == "docx":
        return f"{name}.docx", to_docx(doc, cit), DOCX_MEDIA
    if fmt == "md":
        return f"{name}.md", to_markdown(doc, cit), "text/markdown; charset=utf-8"
    raise ValueError("Unbekanntes Format")
