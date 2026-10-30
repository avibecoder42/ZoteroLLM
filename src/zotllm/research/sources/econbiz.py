"""EconBiz (Wirtschaft, ZBW): REST-API v1 ohne Schlüssel, Lucene-Syntax (``title:``, ``date:[2010 TO 2026]``).

Die Suche liefert keine Abstracts; die App holt sie über DOI nach (Abstracts nachladen). ``from`` zählt ab 1.
Die Nutzungsbedingungen bitten um Zurückhaltung: keine Massenkopien.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..http import Http
from ..records import DOI_RE
from . import SearchResult
from .ris import split_name

BASE = "https://api.econbiz.de/v1/search"
PAGE = 100
DEFAULT_MAX = 500
TYPES = {"article": "journalArticle", "book": "book", "article in book": "bookSection", "chapter": "bookSection",
         "thesis": "thesis", "report": "report", "working paper": "report", "conference paper": "conferencePaper"}


def _with_limits(q: str, limits: dict | None) -> str:
    limits = limits or {}
    y1, y2 = limits.get("year_from"), limits.get("year_to")
    if y1 or y2:
        q = f"({q}) AND date:[{y1 or 1800} TO {y2 or 3000}]"
    return q


class EconBiz:
    source = "econbiz"

    def __init__(self, http: Http):
        self.http = http

    def _get(self, q: str, limits: dict | None, size: int, start: int = 1) -> dict:
        return self.http.get_json(BASE, params={"q": _with_limits(q, limits), "size": size, "from": start,
                                                "sort": "score desc"})["hits"]

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        return SearchResult(int(self._get(q, limits, 0)["total"]),
                            warnings=["EconBiz liefert keine Abstracts – nach der Suche „Abstracts nachladen“."])

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        records, start, count = [], 1, 0
        while len(records) < n_max:
            h = self._get(q, limits, min(PAGE, n_max - len(records)), start)
            count = int(h["total"])
            hits = h.get("hits") or []
            records += [to_rec(x) for x in hits]
            start += len(hits)
            if progress:
                progress(len(records), min(count, n_max))
            if not hits or start > count:
                break
        warnings = ["EconBiz liefert keine Abstracts – nach der Suche „Abstracts nachladen“."]
        if count > n_max:
            warnings.append(f"{count} Treffer, geholt wurden die {n_max} relevantesten.")
        return SearchResult(count, records[:n_max], warnings=warnings)


def to_rec(h: dict) -> dict:
    urls = h.get("identifier_url") or []
    doi = next((m.group(0) for u in urls for m in [DOI_RE.search(u)] if m), "")
    part_of = (h.get("isPartOf") or [""])[0]
    container = part_of.split(" ; ")[0].split(". - ")[0].strip()
    date = (h.get("date") or [""])[0]
    year = re.search(r"\d{4}", date)
    itype = TYPES.get((h.get("type") or "").lower(), "journalArticle")
    names = list(dict.fromkeys((h.get("creator") or []) + (h.get("contributor") or [])))
    return {
        "type": itype,
        "title": (h.get("title") or "").replace(" : ", ": "),
        "authors": [split_name(n) if "," in n else ["", n] for n in names],
        "container": container,
        "date": date,
        "year": int(year.group(0)) if year else None,
        "doi": doi,
        "abstract": h.get("abstract") or "",
        "accession": f"econbiz:{h.get('id')}" if h.get("id") else "",
        "subjects": list(h.get("subject") or []),
        "url": f"https://www.econbiz.de/Record/{h['id']}" if h.get("id") else "",
    }
