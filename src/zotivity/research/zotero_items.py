"""Datensatz → Zotero-Eintrag (JSON der Zotero-API), aus litsearch.py übernommen; dazu Schlagwörter."""

from __future__ import annotations

FIELDS = {
    "journalArticle": {"container": "publicationTitle", "journal_abbr": "journalAbbreviation", "volume": "volume",
                       "issue": "issue", "pages": "pages", "doi": "DOI", "issn": "ISSN"},
    "conferencePaper": {"container": "proceedingsTitle", "volume": "volume", "pages": "pages", "doi": "DOI",
                        "isbn": "ISBN", "publisher": "publisher", "place": "place"},
    "book": {"publisher": "publisher", "place": "place", "isbn": "ISBN", "volume": "volume"},
    "bookSection": {"container": "bookTitle", "publisher": "publisher", "place": "place", "isbn": "ISBN",
                    "pages": "pages"},
    "thesis": {"publisher": "university", "place": "place"},
    "report": {"publisher": "institution", "place": "place", "pages": "pages"},
}
TAG = "litsearch"


def _creator(role: str, last: str, first: str) -> dict:
    if last:
        return {"creatorType": role, "lastName": last, "firstName": first}
    return {"creatorType": role, "name": first}


def to_zotero(rec: dict, collections: list[str], catalog: str, tags: list[str] | None = None) -> dict:
    itype = rec.get("type") if rec.get("type") in FIELDS else "journalArticle"
    creators = [_creator("author", *a[:2]) for a in rec.get("authors") or [] if len(a) >= 2]
    if itype in ("book", "bookSection", "conferencePaper"):
        creators += [_creator("editor", *e[:2]) for e in rec.get("editors") or [] if len(e) >= 2]
    item = {
        "itemType": itype,
        "title": rec.get("title", ""),
        "creators": creators,
        "date": rec.get("date") or (str(rec["year"]) if rec.get("year") else ""),
        "abstractNote": rec.get("abstract", ""),
        "url": "" if rec.get("doi") else rec.get("url", ""),
        "language": rec.get("lang", ""),
        "libraryCatalog": catalog,
        "collections": list(collections),
        "tags": [{"tag": t} for t in [TAG, *(tags or [])]],
    }
    for key, field in FIELDS[itype].items():
        if rec.get(key):
            item[field] = rec[key]
    extra = []
    if rec.get("doi") and "doi" not in FIELDS[itype]:
        extra.append(f"DOI: {rec['doi']}")
    if rec.get("pmid"):
        extra.append(f"PMID: {rec['pmid']}")
    if rec.get("pmcid"):
        extra.append(f"PMCID: {rec['pmcid']}")
    if rec.get("openalex_id"):
        extra.append(f"OpenAlex: {rec['openalex_id']}")
    if rec.get("accession"):
        extra.append(f"Accession: {rec['accession']}")
    item["extra"] = "\n".join(extra)
    return item
