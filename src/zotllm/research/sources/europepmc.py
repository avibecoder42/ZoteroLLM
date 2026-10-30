"""Europe PMC (Lebenswissenschaften, Gesundheit, auch Preprints): REST-Suche, ohne Schlüssel.

Syntax wie Lucene: ``TITLE:``, ``ABSTRACT:``, ``MESH:``, AND/OR/NOT, ``*`` am Wortende, Phrasen in Anführungszeichen.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..http import Http
from . import SearchResult
from .pubmed import _lang

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PAGE = 1000
DEFAULT_MAX = 2000


def _with_limits(q: str, limits: dict | None) -> str:
    limits = limits or {}
    y1, y2 = limits.get("year_from"), limits.get("year_to")
    if y1 or y2:
        q = f"({q}) AND PUB_YEAR:[{y1 or 1800} TO {y2 or 3000}]"
    return q


class EuropePMC:
    source = "europepmc"

    def __init__(self, http: Http, email: str | None = None):
        self.http = http
        self.email = email

    def _params(self, q: str, limits: dict | None, **extra) -> dict:
        p = {"query": _with_limits(q, limits), "format": "json", **extra}
        if self.email:
            p["email"] = self.email
        return p

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        d = self.http.get_json(BASE, params=self._params(q, limits, pageSize=1, resultType="idlist"))
        return SearchResult(int(d.get("hitCount") or 0))

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        records, cursor, count = [], "*", 0
        while cursor and len(records) < n_max:
            d = self.http.get_json(BASE, params=self._params(q, limits, pageSize=min(PAGE, n_max - len(records)),
                                                            resultType="core", cursorMark=cursor))
            count = int(d.get("hitCount") or 0)
            page = (d.get("resultList") or {}).get("result") or []
            records += [to_rec(r) for r in page]
            nxt = d.get("nextCursorMark")
            cursor = nxt if page and nxt and nxt != cursor else None
            if progress:
                progress(len(records), min(count, n_max))
        warnings = [f"{count} Treffer, geholt wurden {n_max}."] if count > n_max else []
        return SearchResult(count, records[:n_max], warnings=warnings)


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def to_rec(r: dict) -> dict:
    ji = r.get("journalInfo") or {}
    journal = ji.get("journal") or {}
    authors = []
    for a in (r.get("authorList") or {}).get("author") or []:
        if a.get("lastName"):
            authors.append([a["lastName"], a.get("firstName") or a.get("initials") or ""])
        elif a.get("collectiveName") or a.get("fullName"):
            authors.append(["", a.get("collectiveName") or a.get("fullName")])
    subjects = [m.get("descriptorName") for m in (r.get("meshHeadingList") or {}).get("meshHeading") or []]
    subjects += list((r.get("keywordList") or {}).get("keyword") or [])
    is_preprint = r.get("source") == "PPR"
    return {
        "type": "preprint" if is_preprint else "journalArticle",
        "title": _strip_tags(r.get("title") or "").rstrip("."),
        "authors": authors,
        "container": journal.get("title") or ("Preprint" if is_preprint else ""),
        "journal_abbr": journal.get("isoabbreviation") or "",
        "volume": ji.get("volume") or "",
        "issue": ji.get("issue") or "",
        "pages": r.get("pageInfo") or "",
        "date": r.get("firstPublicationDate") or str(r.get("pubYear") or ""),
        "year": int(r["pubYear"]) if str(r.get("pubYear") or "").isdigit() else None,
        "doi": r.get("doi") or "",
        "issn": journal.get("issn") or journal.get("essn") or "",
        "abstract": _strip_tags(r.get("abstractText") or ""),
        "pmid": r.get("pmid") or "",
        "pmcid": r.get("pmcid") or "",
        "lang": _lang(r.get("language") or ""),
        "subjects": [s for s in subjects if s],
        "cited_by": r.get("citedByCount"),
        "url": f"https://europepmc.org/article/{r.get('source')}/{r.get('id')}" if r.get("id") else "",
    }
