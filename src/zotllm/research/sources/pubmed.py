"""PubMed über die NCBI E-utilities (aus litsearch.py übernommen, auf httpx umgestellt).

esearch mit History-Server liefert Trefferzahl und PubMed-Übersetzung, efetch die Datensätze in Stapeln von 200.
Ohne NCBI-Schlüssel sind 3 Anfragen pro Sekunde erlaubt, mit Schlüssel 10.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

from ..errors import SourceError
from ..http import Http
from ..records import norm_doi
from . import SearchResult

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
PUBMED_LIMIT = 10000  # E-utilities liefert pro Suche höchstens 10'000 Datensätze
BATCH = 200


class PubMed:
    source = "pubmed"

    def __init__(self, http: Http, api_key: str | None = None, email: str | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.http = http
        self.sleep = sleep
        self.extra = {"tool": "litsearch"}
        if api_key:
            self.extra["api_key"] = api_key
        if email:
            self.extra["email"] = email
        self.delay = 0.12 if api_key else 0.4

    def _call(self, util: str, params: dict) -> bytes:
        self.sleep(self.delay)
        return self.http.request("POST", EUTILS + util, data={**params, **self.extra}).content

    @staticmethod
    def _limits(limits: dict | None) -> dict:
        limits = limits or {}
        out = {}
        if limits.get("year_from") or limits.get("year_to"):
            out = {"datetype": "pdat", "mindate": str(limits.get("year_from") or 1800),
                   "maxdate": str(limits.get("year_to") or 3000)}
        return out

    def _esearch(self, term: str, limits: dict | None) -> dict:
        raw = self._call("esearch.fcgi", {"db": "pubmed", "term": term, "usehistory": "y", "retmax": 0,
                                          "retmode": "json", **self._limits(limits)})
        try:
            res = json.loads(raw)["esearchresult"]
        except (ValueError, KeyError) as e:
            raise SourceError(f"PubMed: unerwartete Antwort ({e})") from None
        if "ERROR" in res:
            raise SourceError("PubMed: " + res["ERROR"])
        return res

    @staticmethod
    def _warnings(res: dict) -> list[str]:
        out = []
        for kind in ("errorlist", "warninglist"):
            for name, vals in (res.get(kind) or {}).items():
                if vals:
                    out.append(f"{name}: {', '.join(map(str, vals))}")
        return out

    def count(self, term: str, limits: dict | None = None) -> SearchResult:
        res = self._esearch(term, limits)
        return SearchResult(int(res["count"]), translation=res.get("querytranslation", ""), warnings=self._warnings(res))

    def search(self, term: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        res = self._esearch(term, limits)
        count = int(res["count"])
        warnings = self._warnings(res)
        n = min(count, max_records or PUBMED_LIMIT, PUBMED_LIMIT)
        if count > PUBMED_LIMIT and n == PUBMED_LIMIT:
            warnings.append(f"PubMed liefert über die API höchstens {PUBMED_LIMIT} Datensätze – Suche eingrenzen.")
        records = []
        for start in range(0, n, BATCH):
            xml = self._call("efetch.fcgi", {"db": "pubmed", "query_key": res["querykey"], "WebEnv": res["webenv"],
                                             "retstart": start, "retmax": min(BATCH, n - start), "retmode": "xml"})
            try:
                root = ET.fromstring(xml)
            except ET.ParseError as e:
                raise SourceError(f"PubMed: Antwort nicht lesbar ({e})") from None
            for el in root:
                rec = parse_pubmed(el)
                if rec:
                    records.append(rec)
            if progress:
                progress(min(start + BATCH, n), n)
        return SearchResult(count, records, res.get("querytranslation", ""), warnings)

    # -- für „Abstracts nachladen“ ------------------------------------------------------------------
    def by_pmids(self, pmids: list[str]) -> dict[str, dict]:
        out = {}
        for i in range(0, len(pmids), BATCH):
            xml = self._call("efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids[i:i + BATCH]), "retmode": "xml"})
            try:
                root = ET.fromstring(xml)
            except ET.ParseError:
                continue
            for el in root:
                rec = parse_pubmed(el)
                if rec and rec.get("pmid"):
                    out[rec["pmid"]] = rec
        return out

    def by_dois(self, dois: list[str]) -> dict[str, dict]:
        """DOI → PubMed-Datensatz (für Treffer anderer Quellen, die in PubMed stehen)."""
        out = {}
        for i in range(0, len(dois), 50):
            chunk = dois[i:i + 50]
            term = " OR ".join(f'"{d}"[doi]' for d in chunk)
            raw = self._call("esearch.fcgi", {"db": "pubmed", "term": term, "retmax": 200, "retmode": "json"})
            try:
                ids = json.loads(raw)["esearchresult"].get("idlist") or []
            except (ValueError, KeyError):
                continue
            for rec in self.by_pmids(ids).values():
                if rec.get("doi"):
                    out[norm_doi(rec["doi"])] = rec
        return out


def _txt(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _authors(parent) -> list[list[str]]:
    out = []
    for a in parent.findall("AuthorList/Author") if parent is not None else []:
        if a.findtext("CollectiveName"):
            out.append(["", _txt(a.find("CollectiveName"))])
        elif a.findtext("LastName"):
            out.append([a.findtext("LastName"), a.findtext("ForeName") or a.findtext("Initials") or ""])
    return out


def _date(pd) -> str:
    if pd is None:
        return ""
    parts = [pd.findtext(t) for t in ("Year", "Month", "Day")]
    return " ".join(p for p in parts if p) or pd.findtext("MedlineDate") or ""


def parse_pubmed(el) -> dict | None:
    ids = {aid.get("IdType"): (aid.text or "").strip() for aid in el.findall("PubmedData/ArticleIdList/ArticleId")}
    if el.tag == "PubmedArticle":
        mc = el.find("MedlineCitation")
        art = mc.find("Article")
        journal = art.find("Journal")
        issue = journal.find("JournalIssue") if journal is not None else None
        abstract = []
        for t in art.findall("Abstract/AbstractText"):
            label = t.get("Label")
            abstract.append(f"{label}: {_txt(t)}" if label else _txt(t))
        doi = ids.get("doi") or _txt(art.find("ELocationID[@EIdType='doi']"))
        date = _date(issue.find("PubDate") if issue is not None else None)
        if not re.search(r"\d{4}", date):
            ad = art.find("ArticleDate")
            date = "-".join(ad.findtext(t) or "" for t in ("Year", "Month", "Day")) if ad is not None else date
        subjects = [_txt(m.find("DescriptorName")) for m in mc.findall("MeshHeadingList/MeshHeading")]
        subjects += [_txt(k) for k in mc.findall("KeywordList/Keyword")]
        return {
            "type": "journalArticle",
            "title": _txt(art.find("ArticleTitle")).rstrip(".") or _txt(art.find("VernacularTitle")),
            "authors": _authors(art),
            "container": _txt(journal.find("Title")) if journal is not None else "",
            "journal_abbr": _txt(journal.find("ISOAbbreviation")) if journal is not None else "",
            "volume": issue.findtext("Volume", "") if issue is not None else "",
            "issue": issue.findtext("Issue", "") if issue is not None else "",
            "pages": art.findtext("Pagination/MedlinePgn", ""),
            "date": date,
            "doi": doi,
            "issn": journal.findtext("ISSN", "") if journal is not None else "",
            "abstract": "\n".join(abstract),
            "pmid": mc.findtext("PMID", ""),
            "pmcid": ids.get("pmc", ""),
            "lang": _lang(art.findtext("Language", "")),
            "subjects": [s for s in subjects if s],
        }
    if el.tag == "PubmedBookArticle":
        doc = el.find("BookDocument")
        book = doc.find("Book")
        return {
            "type": "book",
            "title": _txt(doc.find("ArticleTitle")) or _txt(book.find("BookTitle")),
            "authors": _authors(doc) or _authors(book),
            "publisher": book.findtext("Publisher/PublisherName", ""),
            "place": book.findtext("Publisher/PublisherLocation", ""),
            "date": _date(book.find("PubDate")),
            "doi": ids.get("doi", ""),
            "abstract": "\n".join(_txt(t) for t in doc.findall("Abstract/AbstractText")),
            "pmid": doc.findtext("PMID", ""),
        }
    return None


# PubMed nennt Sprachen mit drei Buchstaben, OpenAlex mit zwei
_LANG3 = {"eng": "en", "ger": "de", "deu": "de", "fre": "fr", "fra": "fr", "spa": "es", "ita": "it", "por": "pt",
          "dut": "nl", "nld": "nl", "chi": "zh", "zho": "zh", "jpn": "ja", "kor": "ko", "rus": "ru", "pol": "pl",
          "tur": "tr", "swe": "sv", "dan": "da", "nor": "no", "fin": "fi", "cze": "cs", "ces": "cs", "gre": "el"}


def _lang(code: str) -> str:
    code = (code or "").strip().lower()
    return _LANG3.get(code, code[:2] if len(code) == 2 else code)
