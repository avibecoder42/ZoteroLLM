"""Datenquellen. Direkt durchsuchbar sind die Quellen in ``LIVE_SOURCES``; RIS-Dateien (Ovid, WoS, EBSCO, ProQuest)
kommen über den Import, Crossref vervollständigt die Angaben über die DOI. Welche Datenbank für welche Disziplin
taugt und was sie erlaubt, steht im Katalog (``catalog.py``)."""

from __future__ import annotations

from dataclasses import dataclass, field

SOURCES = {
    "pubmed": "PubMed",
    "openalex": "OpenAlex",
    "europepmc": "Europe PMC",
    "semanticscholar": "Semantic Scholar",
    "eric": "ERIC",
    "econbiz": "EconBiz",
    "arxiv": "arXiv",
    "osf": "OSF-Preprints",
    "swisscovery": "swisscovery",
    "psycinfo": "APA PsycInfo (Ovid)",
    "wos": "Web of Science",
    "scopus": "Scopus",
    "cinahl": "CINAHL",
    "socindex": "SocINDEX",
    "assia": "ASSIA",
    "socabs": "Sociological Abstracts",
    "fis": "FIS Bildung",
    "ris": "RIS-Import",
}
# mit Trefferzahl-Vorschau und direkter Suche
LIVE_SOURCES = ("pubmed", "openalex", "europepmc", "semanticscholar", "eric", "econbiz", "arxiv", "osf", "swisscovery")


def source_label(source: str) -> str:
    return SOURCES.get(source, source)


@dataclass
class SearchResult:
    count: int
    records: list[dict] = field(default_factory=list)
    translation: str = ""
    warnings: list[str] = field(default_factory=list)
    upper_bound: bool = False  # Trefferzahl ist nur eine Obergrenze (z. B. swisscovery mit mehreren Blöcken)
