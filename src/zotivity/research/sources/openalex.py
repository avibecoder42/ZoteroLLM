"""OpenAlex: Boolesche Suche in Titel und Abstract (``title_and_abstract.search``), wie in openalex_search.py.

OpenAlex sucht mit Wortstämmen, kennt aber keine Platzhalter (``*``). Kommas trennen in OpenAlex die Filter und
dürfen deshalb nicht im Suchstring stehen.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..http import Http
from ..records import split_display_name
from . import SearchResult

BASE = "https://api.openalex.org/works"
SELECT = ("id,ids,doi,display_name,publication_year,publication_date,authorships,primary_location,biblio,"
          "abstract_inverted_index,type,language,cited_by_count")
PER_PAGE = 200
DEFAULT_MAX = 200  # wie im Skript: je Suchstring die 200 relevantesten Treffer

TYPES = {"article": "journalArticle", "review": "journalArticle", "book-chapter": "bookSection", "book": "book",
         "dissertation": "thesis", "report": "report", "preprint": "journalArticle"}


def clean_query(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").replace(",", " ")).strip()


class OpenAlex:
    source = "openalex"

    def __init__(self, http: Http, mailto: str | None = None, api_key: str | None = None):
        self.http = http
        self.mailto = mailto
        self.api_key = api_key

    def _filter(self, q: str, limits: dict | None) -> str:
        limits = limits or {}
        parts = [f"title_and_abstract.search:{clean_query(q)}"]
        types = limits.get("types")
        if types:
            parts.append("type:" + "|".join(types))
        if limits.get("year_from"):
            parts.append(f"publication_year:>{int(limits['year_from']) - 1}")
        if limits.get("year_to"):
            parts.append(f"publication_year:<{int(limits['year_to']) + 1}")
        if limits.get("languages"):
            parts.append("language:" + "|".join(limits["languages"]))
        return ",".join(parts)

    def _params(self, q: str, limits: dict | None, **extra) -> dict:
        params = {"filter": self._filter(q, limits), **extra}
        if self.mailto:
            params["mailto"] = self.mailto
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        data = self.http.get_json(BASE, params=self._params(q, limits, **{"per-page": 1, "select": "id"}))
        return SearchResult(int(data["meta"]["count"]), warnings=_warnings(q))

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        records, cursor, count = [], "*", 0
        while cursor and len(records) < n_max:
            per_page = min(PER_PAGE, n_max - len(records))
            data = self.http.get_json(BASE, params=self._params(
                q, limits, **{"per-page": per_page, "sort": "relevance_score:desc", "select": SELECT, "cursor": cursor}))
            count = int(data["meta"]["count"])
            page = data.get("results") or []
            records += [work_to_rec(w) for w in page]
            cursor = data["meta"].get("next_cursor") if page else None
            if progress:
                progress(len(records), min(count, n_max))
        warnings = _warnings(q)
        if count > n_max:
            warnings.append(f"{count} Treffer, geholt wurden die {n_max} relevantesten.")
        return SearchResult(count, records[:n_max], warnings=warnings)


def _warnings(q: str) -> list[str]:
    out = []
    if "*" in q:
        out.append("OpenAlex kennt keine Platzhalter (*) – sie werden ignoriert. Wortformen ggf. ausschreiben.")
    if "," in q:
        out.append("Kommas wurden entfernt (OpenAlex trennt damit Filter).")
    return out


def abstract_from_index(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = {}
    for word, places in inv.items():
        for p in places:
            pos[p] = word
    return " ".join(pos[i] for i in sorted(pos))


def work_to_rec(w: dict) -> dict:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    ids = w.get("ids") or {}
    biblio = w.get("biblio") or {}
    pages = "-".join(p for p in (biblio.get("first_page"), biblio.get("last_page")) if p)
    pmid = (ids.get("pmid") or "").rstrip("/").rsplit("/", 1)[-1]
    issn = src.get("issn_l") or ((src.get("issn") or [""])[0] if src.get("issn") else "")
    authors = [split_display_name((a.get("author") or {}).get("display_name", "")) for a in w.get("authorships") or []]
    return {
        "type": TYPES.get(w.get("type") or "", "journalArticle"),
        "title": w.get("display_name") or w.get("title") or "",
        "authors": [a for a in authors if a[0] or a[1]],
        "authors_split": True,  # Namen nur als Ganzes geliefert – Crossref oder PubMed haben sie genauer
        "container": src.get("display_name") or "",
        "volume": biblio.get("volume") or "",
        "issue": biblio.get("issue") or "",
        "pages": pages,
        "date": w.get("publication_date") or str(w.get("publication_year") or ""),
        "year": w.get("publication_year"),
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "issn": issn or "",
        "abstract": abstract_from_index(w.get("abstract_inverted_index")),
        "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1],
        "pmid": pmid,
        "lang": w.get("language") or "",
        "cited_by": w.get("cited_by_count"),
        "source_type": src.get("type") or "",
    }
