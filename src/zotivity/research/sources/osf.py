"""OSF-Preprints (PsyArXiv, SocArXiv, EdArXiv u. a.) über die SHARE-Suche von OSF (``share.osf.io/trove``).

Die Suche ist einfach: Alle Stichwörter müssen vorkommen, Phrasen in Anführungszeichen gehen; ODER, NICHT und Klammern
nicht. Für ein ODER mehrere kurze Suchstrings anlegen. Ohne Schlüssel.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..http import Http
from ..records import DOI_RE, split_display_name
from . import SearchResult

API = "https://share.osf.io/trove/index-card-search"
PAGE = 100
DEFAULT_MAX = 300
PROVIDERS = {"psyarxiv": "PsyArXiv", "socarxiv": "SocArXiv", "edarxiv": "EdArXiv", "osf": "OSF Preprints",
             "metaarxiv": "MetaArXiv", "lawarxiv": "LawArXiv"}
SIMPLE = "OSF sucht einfach: alle Stichwörter müssen vorkommen; ODER, NICHT und Klammern gehen nicht."


def _warnings(q: str) -> list[str]:
    return [SIMPLE] if re.search(r"\b(OR|AND|NOT)\b|[()]", q) else []


class OSFPreprints:
    source = "osf"

    def __init__(self, http: Http):
        self.http = http

    def _params(self, q: str, limits: dict | None, size: int) -> dict:
        p = {"cardSearchText": q, "cardSearchFilter[resourceType]": "Preprint", "page[size]": size}
        providers = (limits or {}).get("providers") or []
        if providers:
            p["cardSearchFilter[publisher][any-of]"] = ",".join(f"https://osf.io/preprints/{x}" for x in providers)
        return p

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        d = self.http.get_json(API, params=self._params(q, limits, 1), headers={"Accept": "application/json"})
        return SearchResult(int((d.get("meta") or {}).get("total") or 0), warnings=_warnings(q))

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        url, params = API, self._params(q, limits, min(PAGE, n_max))
        records, count = [], 0
        while url and len(records) < n_max:
            d = self.http.get_json(url, params=params, headers={"Accept": "application/json"})
            count = int((d.get("meta") or {}).get("total") or 0)
            page = d.get("data") or []
            records += [to_rec(x) for x in page]
            url, params = (d.get("links") or {}).get("next"), None
            if progress:
                progress(len(records), min(count, n_max))
            if not page:
                break
        warnings = _warnings(q) + ([f"{count} Treffer, geholt wurden {n_max}."] if count > n_max else [])
        return SearchResult(count, records[:n_max], warnings=warnings)


def _vals(item: dict, key: str) -> list[str]:
    return [v.get("@value") for v in item.get(key) or [] if isinstance(v, dict) and v.get("@value")]


def to_rec(item: dict) -> dict:
    ids = _vals(item, "identifier") + [s.get("@id", "") for s in item.get("sameAs") or [] if isinstance(s, dict)]
    doi = next((m.group(0) for i in ids for m in [DOI_RE.search(i)] if m), "")
    pub = (item.get("publisher") or [{}])[0]
    pub_name = (_vals(pub, "name") or [""])[0] if isinstance(pub, dict) else ""
    date = (_vals(item, "dateCreated") or _vals(item, "dateCopyrighted") or [""])[0]
    authors = []
    for c in item.get("creator") or []:
        name = (_vals(c, "name") or [""])[0] if isinstance(c, dict) else ""
        if name:
            authors.append(split_display_name(name))
    return {
        "type": "preprint",
        "title": (_vals(item, "title") or [""])[0],
        "authors": authors,
        "authors_split": True,
        "container": pub_name or "OSF Preprints",
        "publisher": pub_name,
        "date": date,
        "year": int(date[:4]) if date[:4].isdigit() else None,
        "doi": doi,
        "abstract": (_vals(item, "description") or [""])[0],
        "subjects": _vals(item, "keyword"),
        "url": item.get("@id") or "",
    }
