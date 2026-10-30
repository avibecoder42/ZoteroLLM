"""RIS-Import (Ovid PsycInfo, Web of Science, EBSCO) – aus litsearch.py übernommen, ergänzt um Schlagwörter
(KW, bei Ovid die PsycInfo-Schlagwörter), Sprache (LA) und Accession Number (AN)."""

from __future__ import annotations

import re

from ..records import DOI_RE, norm_doi

RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])\s{1,2}-\s?(.*)$")
RIS_TYPES = {
    "JOUR": "journalArticle", "JFULL": "journalArticle", "EJOUR": "journalArticle",
    "MGZN": "journalArticle", "NEWS": "journalArticle",
    "BOOK": "book", "EBOOK": "book", "EDBOOK": "book",
    "CHAP": "bookSection", "ECHAP": "bookSection",
    "CONF": "conferencePaper", "CPAPER": "conferencePaper",
    "THES": "thesis", "RPRT": "report",
}
LANGS = {"english": "en", "german": "de", "french": "fr", "spanish": "es", "italian": "it", "portuguese": "pt",
         "dutch": "nl", "chinese": "zh", "japanese": "ja", "korean": "ko", "russian": "ru", "polish": "pl",
         "turkish": "tr", "swedish": "sv"}


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")  # pragma: no cover - latin-1 dekodiert alles


def read_ris(text: str) -> list[dict[str, list[str]]]:
    records, cur, last = [], None, None
    for line in text.splitlines():
        m = RIS_LINE.match(line.rstrip())
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if tag == "TY":
                cur = {}
            if cur is None:
                continue
            if tag == "ER":
                records.append(cur)
                cur, last = None, None
                continue
            cur.setdefault(tag, []).append(val)
            last = tag
        elif cur is not None and last and line.strip():
            cur[last][-1] += " " + line.strip()  # umgebrochene Zeilen (z. B. lange Abstracts)
    if cur:
        records.append(cur)
    return records


def split_name(name: str) -> list[str]:
    name = name.strip()
    if "," in name:
        last, first = name.split(",", 1)
        return [last.strip(), first.strip()]
    return ["", name]


def _lang(value: str) -> str:
    v = value.strip().lower()
    return LANGS.get(v, v[:2] if len(v) == 2 else v)


def ris_to_rec(r: dict[str, list[str]]) -> dict:
    def first(*tags):
        return next((r[t][0] for t in tags if r.get(t) and r[t][0]), "")

    itype = RIS_TYPES.get(first("TY").upper(), "journalArticle")
    title = first("TI", "T1", "CT")
    if itype == "bookSection":
        container = first("T2", "BT", "JF", "JO")
    elif itype == "book":
        title, container = title or first("BT"), ""
    else:
        container = first("T2", "JF", "JO", "JFULL", "BT")

    doi = first("DO")
    if not doi:
        for tag in ("M3", "UR", "L1", "L2", "L3", "N1", "AN", "ID"):
            m = next((DOI_RE.search(v) for v in r.get(tag, []) if DOI_RE.search(v)), None)
            if m:
                doi = m.group(0)
                break
    doi = norm_doi(doi) if doi else ""

    # Ovid schreibt Daten als "2020//" oder "2020/03/15/"
    raw_date = first("PY", "Y1", "DA")
    date = "-".join(p for p in raw_date.split("/")[:3] if p.strip()) if "/" in raw_date else raw_date

    sp, ep = first("SP"), first("EP")
    sn = first("SN")
    is_book = itype in ("book", "bookSection")
    subjects = [k for t in ("KW", "MH", "ST") for v in r.get(t, []) for k in re.split(r"\s*;\s*", v) if k]
    return {
        "type": itype,
        "title": title,
        "authors": [split_name(a) for t in ("AU", "A1") for a in r.get(t, []) if a],
        "editors": [split_name(a) for t in ("A2", "ED") for a in r.get(t, []) if a] if is_book else [],
        "container": container,
        "journal_abbr": first("J2", "JA"),
        "volume": first("VL"),
        "issue": first("IS"),
        "pages": sp if not ep or "-" in sp else f"{sp}-{ep}",
        "date": date,
        "doi": doi,
        "issn": "" if is_book else sn,
        "isbn": sn if is_book else "",
        "abstract": first("AB", "N2"),
        "publisher": first("PB"),
        "place": first("CY", "PP"),
        "url": first("UR", "L2"),
        "accession": first("AN"),
        "lang": _lang(first("LA")),
        "subjects": subjects,
    }


def parse(raw: bytes | str) -> list[dict]:
    text = decode(raw) if isinstance(raw, bytes) else raw
    return [ris_to_rec(r) for r in read_ris(text)]
