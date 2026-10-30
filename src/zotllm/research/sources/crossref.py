"""Crossref: vollständige Angaben über die DOI (Zeitschrift, Band, Heft, Seiten, Autor*innen mit Vornamen)."""

from __future__ import annotations

import re
from urllib.parse import quote

from ..errors import SourceError
from ..http import Http
from ..records import merge, norm_doi

BASE = "https://api.crossref.org/works/"
TYPES = {"journal-article": "journalArticle", "book-chapter": "bookSection", "book-section": "bookSection",
         "book": "book", "monograph": "book", "edited-book": "book", "reference-book": "book",
         "proceedings-article": "conferencePaper", "report": "report", "dissertation": "thesis"}


class Crossref:
    def __init__(self, http: Http, mailto: str | None = None):
        self.http = http
        self.mailto = mailto

    def work(self, doi: str) -> dict | None:
        doi = norm_doi(doi)
        if not doi:
            return None
        params = {"mailto": self.mailto} if self.mailto else None
        r = self.http.request("GET", BASE + quote(doi, safe="/"), params=params, check=False)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise SourceError(f"Crossref {doi}: HTTP {r.status_code}", r.status_code)
        return message_to_rec(r.json().get("message") or {})


def _first(v) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v or "")


def _strip_jats(text: str) -> str:
    text = re.sub(r"<jats:title>.*?</jats:title>", " ", text or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def message_to_rec(m: dict) -> dict:
    parts = ((m.get("issued") or m.get("published") or {}).get("date-parts") or [[]])[0]
    date = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts) if p)
    itype = TYPES.get(m.get("type") or "", "journalArticle")
    authors = [[a.get("family", ""), a.get("given", "")] if a.get("family") else ["", a.get("name", "")]
               for a in m.get("author") or []]
    editors = [[a.get("family", ""), a.get("given", "")] for a in m.get("editor") or [] if a.get("family")]
    issn = _first(m.get("ISSN"))
    isbn = _first(m.get("ISBN"))
    return {
        "type": itype,
        "title": _first(m.get("title")),
        "authors": [a for a in authors if a[0] or a[1]],
        "editors": editors,
        "container": _first(m.get("container-title")),
        "journal_abbr": _first(m.get("short-container-title")),
        "volume": m.get("volume") or "",
        "issue": m.get("issue") or "",
        "pages": m.get("page") or "",
        "date": date,
        "year": parts[0] if parts else None,
        "doi": norm_doi(m.get("DOI") or ""),
        "issn": issn if itype not in ("book", "bookSection") else "",
        "isbn": isbn if itype in ("book", "bookSection") else "",
        "abstract": _strip_jats(m.get("abstract") or ""),
        "publisher": m.get("publisher") or "",
        "lang": (m.get("language") or "")[:2],
    }


def enrich(rec: dict, cr: dict | None) -> dict:
    """Leere Felder aus Crossref füllen. Bei Quellen mit nur ganzen Namen (OpenAlex) die Crossref-Namen nehmen."""
    if not cr:
        return rec
    out = merge(rec, cr)
    if rec.get("authors_split") and cr.get("authors"):
        out["authors"], out["authors_split"] = cr["authors"], False
    if cr.get("container") and (not rec.get("container") or rec.get("container", "").isupper()):
        out["container"] = cr["container"]
    if cr.get("type") and cr["type"] != "journalArticle" and rec.get("type") == "journalArticle" and not rec.get("issn"):
        out["type"] = cr["type"]
    return out
