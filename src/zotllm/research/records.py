"""Datensätze in einheitlicher Form und ihre Duplikat-Schlüssel (aus litsearch.py übernommen und erweitert).

Ein Datensatz ist ein dict mit diesen Feldern (fehlende bleiben leer):
type, title, authors [[Nachname, Vorname], …], editors, container (Zeitschrift/Buch), journal_abbr, volume, issue,
pages, date, year, doi, issn, isbn, abstract, pmid, pmcid, openalex_id, accession (Ovid AN), lang, subjects [..],
publisher, place, url, cited_by.
"""

from __future__ import annotations

import re
import unicodedata

TEXT_FIELDS = ("type", "title", "container", "journal_abbr", "volume", "issue", "pages", "date", "doi", "issn",
               "isbn", "abstract", "pmid", "pmcid", "openalex_id", "accession", "lang", "publisher", "place", "url")
LIST_FIELDS = ("authors", "editors", "subjects")
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
MIN_TITLE = 15  # kürzere Titel („Editorial“) taugen nicht zum Abgleich


def norm_doi(doi: str) -> str:
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", (doi or "").strip().lower())
    return doi.rstrip(".,;)")


def find_dois(text: str) -> list[str]:
    """Alle DOIs in einem Text (auch aus Markdown-Links wie [10.1/x](https://doi.org/10.1/x)), ohne Doppelte."""
    out = []
    for m in re.finditer(r"10\.\d{4,9}/[^\s\"<>\[\]]+", text or ""):
        d = m.group(0).rstrip(".,;:")
        while d.endswith(")") and d.count(")") > d.count("("):
            d = d[:-1]
        d = norm_doi(d)
        if d not in out:
            out.append(d)
    return out


def norm_title(title: str) -> str:
    title = unicodedata.normalize("NFKD", (title or "").lower())
    return "".join(ch for ch in title if ch.isalnum())


def norm_openalex(oid: str) -> str:
    oid = (oid or "").strip()
    return oid.rsplit("/", 1)[-1].upper() if oid else ""


def year_of(rec: dict) -> int | None:
    y = rec.get("year")
    if isinstance(y, int):
        return y
    m = re.search(r"(1[89]|20)\d{2}", str(y or rec.get("date") or ""))
    return int(m.group(0)) if m else None


def normalize(rec: dict) -> dict:
    """Fehlende Felder ergänzen, Kennungen vereinheitlichen."""
    out = {k: (rec.get(k) or "") for k in TEXT_FIELDS}
    for k in LIST_FIELDS:
        out[k] = [list(a) if isinstance(a, (list, tuple)) else a for a in (rec.get(k) or [])]
    out["type"] = out["type"] or "journalArticle"
    out["title"] = re.sub(r"\s+", " ", out["title"]).strip()
    out["doi"] = norm_doi(out["doi"]) if out["doi"] else ""
    out["openalex_id"] = norm_openalex(out["openalex_id"])
    out["pmid"] = str(out["pmid"]).strip()
    out["year"] = year_of(rec)
    out["cited_by"] = rec.get("cited_by")
    for k in ("authors_split",):
        if rec.get(k):
            out[k] = rec[k]
    return out


def dedup_keys(rec: dict) -> set[str]:
    keys = set()
    if rec.get("doi"):
        keys.add("doi:" + norm_doi(rec["doi"]))
    if rec.get("pmid"):
        keys.add("pmid:" + str(rec["pmid"]).strip())
    if rec.get("openalex_id"):
        keys.add("oa:" + norm_openalex(rec["openalex_id"]))
    if rec.get("accession"):
        keys.add("an:" + rec["accession"].strip().lower())
    t = norm_title(rec.get("title", ""))
    if len(t) >= MIN_TITLE:
        keys.add("title:" + t)
    return keys


def dedup_keys_zotero(data: dict) -> set[str]:
    """Schlüssel eines Zotero-Eintrags (data-Teil der API). DOI, PMID usw. stehen bei manchen Arten unter „Extra“."""
    extra = data.get("extra", "") or ""

    def from_extra(label):
        m = re.search(rf"^{label}:\s*(\S+)", extra, re.M | re.I)
        return m.group(1) if m else ""

    return dedup_keys({
        "doi": data.get("DOI") or from_extra("DOI"),
        "pmid": from_extra("PMID"),
        "title": data.get("title", ""),
    })


def years_conflict(a: dict, b: dict) -> bool:
    """Gleicher Titel, aber Jahre weit auseinander: wohl verschiedene Arbeiten (z. B. Erratum, Neuauflage)."""
    ya, yb = year_of(a), year_of(b)
    return bool(ya and yb and abs(ya - yb) > 1)


def merge(base: dict, other: dict) -> dict:
    """Leere Felder von base aus other füllen (z. B. PMID aus PubMed, Abstract aus OpenAlex)."""
    out = dict(base)
    for k in TEXT_FIELDS:
        if not out.get(k) and other.get(k):
            out[k] = other[k]
    for k in LIST_FIELDS:
        if not out.get(k) and other.get(k):
            out[k] = other[k]
    if not out.get("year") and other.get("year"):
        out["year"] = other["year"]
    if out.get("authors_split") and other.get("authors") and not other.get("authors_split"):
        out["authors"], out["authors_split"] = other["authors"], False  # sauber getrennte Namen bevorzugen
    if other.get("cited_by") and not out.get("cited_by"):
        out["cited_by"] = other["cited_by"]
    return out


def split_display_name(name: str) -> list[str]:
    """„Jane M. Doe“ → [Doe, Jane M.] – für Quellen, die Namen nur als Ganzes liefern (OpenAlex)."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        return ["", ""]
    if "," in name:
        last, first = name.split(",", 1)
        return [last.strip(), first.strip()]
    parts = name.split(" ")
    if len(parts) == 1:
        return [parts[0], ""]
    # Namenszusätze wie „van“, „de“ gehören zum Nachnamen
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in ("van", "von", "de", "der", "den", "da", "del", "di", "la", "le", "du"):
        i -= 1
    return [" ".join(parts[i:]), " ".join(parts[:i])]


def first_author(rec: dict) -> str:
    authors = rec.get("authors") or []
    if not authors:
        return ""
    a = authors[0]
    name = (a[0] or a[1]) if isinstance(a, (list, tuple)) else str(a)
    return f"{name} et al." if len(authors) > 2 else (f"{name} & {authors[1][0] or authors[1][1]}" if len(authors) == 2 else name)


def short_ref(rec: dict) -> str:
    """„Doe et al. (2021)“"""
    who = first_author(rec) or "o. A."
    return f"{who} ({year_of(rec) or 'o. J.'})"
