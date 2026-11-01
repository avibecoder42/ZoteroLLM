"""Semantic Scholar (alle Fächer, Schwerpunkt Natur, Technik, Bio): Bulk-Suche der Graph API.

Syntax der Bulk-Suche: ``+`` UND, ``|`` ODER, ``-`` NICHT, ``"Phrase"``, ``*`` am Wortende, Klammern. Gesucht wird in
Titel und Abstract. Ohne Schlüssel teilen sich alle einen kleinen Pool (häufig HTTP 429); mit Schlüssel 1 Anfrage/s.
Nutzung nach dem Lizenzvertrag von AI2 (nicht kommerziell).
"""

from __future__ import annotations

from collections.abc import Callable

from ..errors import SourceError
from ..http import Http
from ..records import split_display_name
from . import SearchResult

BULK = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"
FIELDS = "title,abstract,year,externalIds,venue,journal,authors,publicationTypes,publicationDate,citationCount"
DEFAULT_MAX = 1000
TYPES = {"JournalArticle": "journalArticle", "Review": "journalArticle", "Book": "book", "BookSection": "bookSection",
         "Conference": "conferencePaper", "Dissertation": "thesis"}
NO_KEY = "Semantic Scholar: zu viele Anfragen. Mit einem kostenlosen Schlüssel ([semanticscholar] api_key) geht es zuverlässig."


class SemanticScholar:
    source = "semanticscholar"

    def __init__(self, http: Http, api_key: str | None = None):
        self.http = http
        self.api_key = api_key

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key} if self.api_key else {}

    def _get(self, q: str, limits: dict | None, token: str | None = None) -> dict:
        limits = limits or {}
        params = {"query": q, "fields": FIELDS}
        if limits.get("year_from") or limits.get("year_to"):
            params["year"] = f"{limits.get('year_from') or ''}-{limits.get('year_to') or ''}"
        if token:
            params["token"] = token
        r = self.http.request("GET", BULK, params=params, headers=self._headers(), retries=3 if self.api_key else 2,
                              check=False)
        if r.status_code == 429:
            raise SourceError(NO_KEY, 429)
        if r.status_code >= 400:
            raise SourceError(f"Semantic Scholar: HTTP {r.status_code}: {r.text[:200]}", r.status_code)
        return r.json()

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        return SearchResult(int(self._get(q, limits).get("total") or 0))

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        records, token, count = [], None, 0
        while len(records) < n_max:
            d = self._get(q, limits, token)
            count = int(d.get("total") or 0)
            page = d.get("data") or []
            records += [to_rec(p) for p in page]
            token = d.get("token")
            if progress:
                progress(len(records), min(count, n_max))
            if not page or not token:
                break
        warnings = [f"{count} Treffer, geholt wurden {n_max}."] if count > n_max else []
        return SearchResult(count, records[:n_max], warnings=warnings)

    def abstracts(self, dois: list[str]) -> dict[str, str]:
        """Abstracts für bis zu 500 DOIs auf einmal (für „Abstracts nachladen“)."""
        if not dois:
            return {}
        r = self.http.request("POST", BATCH, params={"fields": "abstract,externalIds"}, headers=self._headers(),
                              json={"ids": [f"DOI:{d}" for d in dois[:500]]}, retries=2, check=False)
        if r.status_code == 429:
            raise SourceError(NO_KEY, 429)
        if r.status_code >= 400:
            raise SourceError(f"Semantic Scholar: HTTP {r.status_code}", r.status_code)
        out = {}
        for doi, p in zip(dois, r.json()):
            if p and p.get("abstract"):
                out[doi] = p["abstract"]
        return out


def to_rec(p: dict) -> dict:
    ext = p.get("externalIds") or {}
    journal = p.get("journal") or {}
    types = p.get("publicationTypes") or []
    itype = next((TYPES[t] for t in types if t in TYPES), "journalArticle")
    return {
        "type": itype,
        "title": p.get("title") or "",
        "authors": [split_display_name(a.get("name", "")) for a in p.get("authors") or [] if a.get("name")],
        "authors_split": True,
        "container": journal.get("name") or p.get("venue") or "",
        "volume": (journal.get("volume") or "").strip(),
        "pages": (journal.get("pages") or "").strip(),
        "date": p.get("publicationDate") or str(p.get("year") or ""),
        "year": p.get("year"),
        "doi": ext.get("DOI") or "",
        "pmid": str(ext.get("PubMed") or ""),
        "abstract": p.get("abstract") or "",
        "cited_by": p.get("citationCount"),
        "accession": f"s2:{p.get('paperId')}" if p.get("paperId") else "",
        "url": f"https://www.semanticscholar.org/paper/{p['paperId']}" if p.get("paperId") else "",
    }
