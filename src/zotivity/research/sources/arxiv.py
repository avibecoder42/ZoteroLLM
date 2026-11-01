"""arXiv (Physik, Informatik, Mathematik, Statistik, quantitative Biologie u. a.): API mit Atom-Antworten.

Syntax: Felder ``ti:``, ``abs:``, ``all:``; AND, OR, ANDNOT; Phrasen in Anführungszeichen; keine Platzhalter.
Nutzungsbedingungen: höchstens eine Anfrage alle 3 Sekunden, eine Verbindung.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

from ..errors import SourceError
from ..http import Http
from ..records import split_display_name
from . import SearchResult

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "os": "http://a9.com/-/spec/opensearch/1.1/",
      "arxiv": "http://arxiv.org/schemas/atom"}
PAGE = 200
DEFAULT_MAX = 500
DELAY = 3.0


def _with_limits(q: str, limits: dict | None) -> str:
    limits = limits or {}
    y1, y2 = limits.get("year_from"), limits.get("year_to")
    if y1 or y2:
        q = f"({q}) AND submittedDate:[{y1 or 1990}01010000 TO {y2 or 2100}12312359]"
    return q


class ArXiv:
    source = "arxiv"

    def __init__(self, http: Http, sleep: Callable[[float], None] = time.sleep):
        self.http = http
        self.sleep = sleep
        self._last = 0.0

    def _get(self, q: str, limits: dict | None, start: int, n: int) -> ET.Element:
        wait = DELAY - (time.monotonic() - self._last)
        if self._last and wait > 0:
            self.sleep(wait)
        r = self.http.request("GET", API, params={"search_query": _with_limits(q, limits), "start": start,
                                                  "max_results": n, "sortBy": "relevance"})
        self._last = time.monotonic()
        try:
            return ET.fromstring(r.content)
        except ET.ParseError as e:
            raise SourceError(f"arXiv: Antwort nicht lesbar ({e})") from None

    @staticmethod
    def _total(root: ET.Element) -> int:
        return int(root.findtext("os:totalResults", "0", NS) or 0)

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        return SearchResult(self._total(self._get(q, limits, 0, 1)), warnings=_warnings(q))  # mit 0 zählt arXiv falsch

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        records, start, count = [], 0, 0
        while len(records) < n_max:
            root = self._get(q, limits, start, min(PAGE, n_max - len(records)))
            count = self._total(root)
            entries = root.findall("a:entry", NS)
            records += [to_rec(e) for e in entries]
            start += len(entries)
            if progress:
                progress(len(records), min(count, n_max))
            if not entries or start >= count:
                break
        warnings = _warnings(q) + ([f"{count} Treffer, geholt wurden die {n_max} relevantesten."] if count > n_max else [])
        return SearchResult(count, records[:n_max], warnings=warnings)


def _warnings(q: str) -> list[str]:
    return ["arXiv kennt keine Platzhalter (*)."] if "*" in q else []


def _text(el, path: str) -> str:
    return re.sub(r"\s+", " ", el.findtext(path, "", NS) or "").strip()


def to_rec(e: ET.Element) -> dict:
    abs_url = _text(e, "a:id")
    arxiv_id = re.sub(r"v\d+$", "", abs_url.rsplit("/abs/", 1)[-1])
    published = _text(e, "a:published")
    journal_ref = _text(e, "arxiv:journal_ref")
    return {
        "type": "preprint",
        "title": _text(e, "a:title"),
        "authors": [split_display_name(_text(a, "a:name")) for a in e.findall("a:author", NS)],
        "authors_split": True,
        "container": journal_ref or "arXiv",
        "date": published[:10],
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "doi": _text(e, "arxiv:doi"),
        "abstract": _text(e, "a:summary"),
        "accession": f"arXiv:{arxiv_id}" if arxiv_id else "",
        "subjects": [c.get("term") for c in e.findall("a:category", NS) if c.get("term")],
        "url": abs_url,
        "publisher": "arXiv",
    }
