"""ERIC (Erziehungswissenschaft, US-Bildungsministerium): offizielle API ohne Schlüssel.

Solr-Syntax: Felder ``title:``, ``description:`` (Abstract), ``subject:`` (Thesaurus), AND/OR/NOT, ``*``.
"""

from __future__ import annotations

from collections.abc import Callable

from ..http import Http
from . import SearchResult
from .ris import LANGS, split_name

BASE = "https://api.ies.ed.gov/eric/"
PAGE = 200
DEFAULT_MAX = 2000
TYPES = (("Journal Articles", "journalArticle"), ("Books", "book"), ("Book", "book"),
         ("Dissertations/Theses", "thesis"), ("Reports", "report"), ("Speeches/Meeting Papers", "conferencePaper"))


def _with_limits(q: str, limits: dict | None) -> str:
    limits = limits or {}
    y1, y2 = limits.get("year_from"), limits.get("year_to")
    if y1 or y2:
        q = f"({q}) AND publicationdateyear:[{y1 or 1800} TO {y2 or 3000}]"
    if limits.get("peer_reviewed"):
        q = f"({q}) AND peerreviewed:T"
    return q


class ERIC:
    source = "eric"

    def __init__(self, http: Http):
        self.http = http

    def _get(self, q: str, limits: dict | None, rows: int, start: int = 0) -> dict:
        return self.http.get_json(BASE, params={"search": _with_limits(q, limits), "format": "json", "rows": rows,
                                                "start": start})["response"]

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        return SearchResult(int(self._get(q, limits, 0)["numFound"]))

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        records, start, count = [], 0, 0
        while len(records) < n_max:
            r = self._get(q, limits, min(PAGE, n_max - len(records)), start)
            count = int(r["numFound"])
            docs = r.get("docs") or []
            records += [to_rec(d) for d in docs]
            start += len(docs)
            if progress:
                progress(len(records), min(count, n_max))
            if not docs or start >= count:
                break
        warnings = [f"{count} Treffer, geholt wurden {n_max}."] if count > n_max else []
        return SearchResult(count, records[:n_max], warnings=warnings)


def _first(v):
    return (v[0] if v else "") if isinstance(v, list) else (v or "")


def to_rec(d: dict) -> dict:
    ptypes = d.get("publicationtype") or []
    itype = next((t for label, t in TYPES if label in ptypes), "journalArticle")
    year = d.get("publicationdateyear")
    lang = _first(d.get("language")).lower()
    issn = _first(d.get("issn")).replace("ISSN-", "")
    isbn = _first(d.get("isbn")).replace("ISBN-", "")
    return {
        "type": itype,
        "title": d.get("title") or "",
        "authors": [split_name(a) if "," in a else ["", a] for a in d.get("author") or []],
        "container": d.get("source") or "",
        "date": str(year or ""),
        "year": int(year) if str(year or "").isdigit() else None,
        "doi": "",
        "issn": issn if itype not in ("book", "bookSection") else "",
        "isbn": isbn if itype in ("book", "bookSection") else "",
        "abstract": d.get("description") or "",
        "publisher": (d.get("publisher") or "").split(". Available from")[0],
        "accession": d.get("id") or "",
        "lang": LANGS.get(lang, lang[:2]),
        "subjects": list(d.get("subject") or []),
        "url": f"https://eric.ed.gov/?id={d['id']}" if d.get("id") else "",
        "peer_reviewed": d.get("peerreviewed") == "T",
    }
