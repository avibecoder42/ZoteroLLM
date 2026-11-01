"""Weitere Eintragsarten für die Vorschau im CSL-Editor.

Welche Arten es gibt, wie sie heissen und wie ihre Felder auf CSL abgebildet werden, kommt aus Zotero selbst (Schema
der lokalen API, zwischengespeichert für die Zeit, in der Zotero nicht läuft). Die Beispiele sind Zotero-Einträge mit
englischen Angaben – erfunden bzw. bekannte Rechtsquellen und Normen – und werden so nach CSL-JSON umgesetzt, wie
Zotero sie an citeproc übergibt. Für Arten ohne eigenes Beispiel (etwa neue in einer späteren Zotero-Version) entsteht
ein allgemeines aus den Feldern der Art.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

from zotivity import paths
from zotivity.zotero import ZoteroError, ZoteroUnavailable

log = logging.getLogger(__name__)

SKIP = {"annotation", "attachment", "note"}
# Schon unter den Standardbeispielen der Vorschau (static/js/core/csl-samples.js)
DEFAULT_TYPES = {"book", "bookSection", "journalArticle", "newspaperArticle", "webpage", "thesis", "report"}
SCHEMA_FRESH_SECONDS = 3600


def _p(kind: str, first: str, last: str) -> dict:
    return {"creatorType": kind, "firstName": first, "lastName": last}


def _org(kind: str, name: str) -> dict:
    return {"creatorType": kind, "name": name}


# Zotero-Felder je Art; „_locator“: Seitenangabe im Beleg
SAMPLES: dict[str, dict] = {
    "artwork": {"title": "Composition with Blue Lines", "artworkMedium": "Oil on canvas", "artworkSize": "92 × 73 cm",
                "date": "1937", "archive": "Museum of Modern Example", "creators": [_p("artist", "Clara", "Mendel")]},
    "audioRecording": {"title": "Northern Lights", "audioRecordingFormat": "CD", "label": "Polar Records", "place": "Oslo",
                       "date": "2019", "runningTime": "52:10", "creators": [_p("performer", "Ingrid", "Solberg")]},
    "bill": {"title": "Digital Services Accountability Act", "billNumber": "H.R. 4521", "code": "H.R.",
             "legislativeBody": "House of Representatives", "session": "118th Congress", "date": "2023-07-12",
             "creators": [_p("sponsor", "Ana", "Reyes")]},
    "blogPost": {"title": "Five lessons from teaching with AI tutors", "blogTitle": "The Learning Lab", "websiteType": "Blog",
                 "date": "2024-05-14", "url": "https://learninglab.example.org/ai-tutors", "accessDate": "2026-10-01",
                 "creators": [_p("author", "Priya", "Raman")]},
    "case": {"caseName": "Brown v. Board of Education", "court": "U.S. Supreme Court", "dateDecided": "1954-05-17",
             "reporter": "U.S.", "reporterVolume": "347", "firstPage": "483", "_locator": "495"},
    "computerProgram": {"title": "TextMiner", "versionNumber": "2.4.1", "date": "2023", "system": "Linux, macOS, Windows",
                        "company": "Open Research Software", "place": "Toronto", "programmingLanguage": "Python",
                        "url": "https://github.com/example/textminer", "creators": [_p("programmer", "Lukas", "Brandt")]},
    "conferencePaper": {"title": "Measuring feedback quality in automated writing support",
                        "proceedingsTitle": "Proceedings of the 14th International Conference on Learning Analytics",
                        "conferenceName": "LAK 2024", "eventPlace": "Kyoto", "publisher": "ACM", "place": "New York",
                        "date": "2024", "pages": "211-220", "DOI": "10.5555/lak.2024.211", "_locator": "214",
                        "creators": [_p("author", "Sofia", "Moreau"), _p("author", "Daniel", "Kim")]},
    "dataset": {"title": "Global Survey on Student Use of Generative AI, Wave 2", "identifier": "GS-AI-2",
                "versionNumber": "2.0", "date": "2025", "repository": "Zenodo", "DOI": "10.5555/zenodo.1234567",
                "creators": [_org("author", "Global Student Survey Consortium")]},
    "dictionaryEntry": {"title": "Plagiarism", "dictionaryTitle": "Oxford Dictionary of Education", "edition": "3",
                        "publisher": "Oxford University Press", "place": "Oxford", "date": "2021", "pages": "412",
                        "creators": [_p("editor", "Susan", "Wallace")]},
    "document": {"title": "Guidelines for the responsible use of AI in research", "date": "2024",
                 "publisher": "International Research Council", "place": "Geneva",
                 "creators": [_org("author", "International Research Council")]},
    "email": {"subject": "Re: Draft chapter 3", "date": "2025-02-03",
              "creators": [_p("author", "Maria", "Lopez"), _p("recipient", "John", "Carter")]},
    "encyclopediaArticle": {"title": "Academic integrity", "encyclopediaTitle": "Encyclopedia of Higher Education",
                            "volume": "2", "publisher": "Springer", "place": "Cham", "date": "2020", "pages": "45-52",
                            "_locator": "47", "creators": [_p("author", "Ahmed", "Hassan"), _p("editor", "Lena", "Fischer")]},
    "film": {"title": "The Last Lecture Hall", "distributor": "Northlight Pictures", "place": "Los Angeles", "date": "2018",
             "genre": "Documentary", "runningTime": "94 min", "creators": [_p("director", "Hannah", "Ito")]},
    "forumPost": {"title": "How do you cite AI-generated text?", "forumTitle": "Academia Stack Exchange",
                  "postType": "Forum post", "date": "2023-11-20", "url": "https://academia.example.org/q/12345",
                  "accessDate": "2026-10-01", "creators": [_p("author", "Tom", "Becker")]},
    "hearing": {"title": "Artificial Intelligence in Education", "committee": "Committee on Education and the Workforce",
                "legislativeBody": "House of Representatives", "session": "118th Congress", "documentNumber": "118-25",
                "publisher": "U.S. Government Publishing Office", "place": "Washington, DC", "pages": "1-84",
                "date": "2023-09-20", "_locator": "12"},
    "instantMessage": {"title": "Message about the project timeline", "date": "2025-01-15",
                       "creators": [_p("author", "Jana", "Novak"), _p("recipient", "Ben", "Ortiz")]},
    "interview": {"title": "Interview on the future of writing instruction", "interviewMedium": "Video call",
                  "date": "2024-04-10", "creators": [_p("interviewee", "Grace", "Owusu"), _p("interviewer", "Martin", "Keller")]},
    "letter": {"title": "Letter to the editorial board", "letterType": "Letter", "date": "1998-06-02",
               "creators": [_p("author", "Eleanor", "Price"), _org("recipient", "Editorial Board, Journal of Example Studies")]},
    "magazineArticle": {"title": "The machines that grade our essays", "publicationTitle": "Science Today",
                        "date": "2024-09", "volume": "38", "issue": "9", "pages": "22-27", "_locator": "24",
                        "creators": [_p("author", "Olivia", "Grant")]},
    "manuscript": {"title": "Notes on a theory of feedback", "manuscriptType": "Unpublished manuscript",
                   "place": "Cambridge, MA", "date": "1987", "numPages": "34", "creators": [_p("author", "Robert", "Hale")]},
    "map": {"title": "Population density of Europe", "mapType": "Thematic map", "scale": "1:5,000,000", "edition": "2",
            "publisher": "Cartographia Press", "place": "Vienna", "date": "2016", "creators": [_p("cartographer", "Karl", "Weiss")]},
    "patent": {"title": "Method for automated assessment of written text", "country": "United States",
               "assignee": "Example Learning Inc.", "issuingAuthority": "U.S. Patent and Trademark Office",
               "patentNumber": "US 11,234,567 B2", "filingDate": "2020-03-15", "issueDate": "2022-02-01",
               "creators": [_p("inventor", "Wei", "Zhang"), _p("inventor", "Laura", "Silva")]},
    "podcast": {"title": "Can AI teach us to write?", "seriesTitle": "Learning Matters", "episodeNumber": "112",
                "audioFileType": "MP3", "date": "2024-10-03", "runningTime": "41 min",
                "url": "https://podcasts.example.org/learning-matters/112", "creators": [_p("podcaster", "Nadia", "Rahman")]},
    "preprint": {"title": "Large language models as writing tutors: A meta-analysis", "genre": "Preprint",
                 "repository": "arXiv", "archiveID": "arXiv:2501.01234", "date": "2025-01-04",
                 "DOI": "10.48550/arXiv.2501.01234", "creators": [_p("author", "Felix", "Wagner"), _p("author", "Aiko", "Sato")]},
    "presentation": {"title": "Feedback at scale: Lessons from ten universities", "presentationType": "Conference presentation",
                     "meetingName": "European Conference on Educational Research", "place": "Lisbon", "date": "2023-08-23",
                     "creators": [_p("presenter", "Marta", "Costa")]},
    "radioBroadcast": {"title": "Writing in the age of algorithms", "programTitle": "Science Hour", "episodeNumber": "45",
                       "network": "BBC Radio 4", "place": "London", "date": "2024-02-11", "runningTime": "28 min",
                       "creators": [_p("host", "Emma", "Clarke")]},
    "standard": {"title": "Information and documentation – Guidelines for bibliographic references and citations to "
                          "information resources", "organization": "International Organization for Standardization",
                 "number": "ISO 690:2021", "edition": "4", "date": "2021", "publisher": "ISO", "place": "Geneva",
                 "numPages": "67"},
    "statute": {"nameOfAct": "Civil Rights Act of 1964", "code": "Stat.", "codeNumber": "78", "publicLawNumber": "Pub. L. 88-352",
                "dateEnacted": "1964-07-02", "pages": "241", "section": "7"},
    "tvBroadcast": {"title": "The Invisible Teacher", "programTitle": "Frontline", "episodeNumber": "12", "network": "PBS",
                    "place": "Boston", "date": "2022-11-08", "runningTime": "54 min", "creators": [_p("director", "Sam", "Okoro")]},
    "videoRecording": {"title": "How peer feedback works", "videoRecordingFormat": "Online video", "studio": "Open Learning Media",
                       "place": "Toronto", "date": "2021", "runningTime": "12 min", "url": "https://video.example.org/peer-feedback",
                       "creators": [_p("director", "Leah", "Morgan")]},
}

# Allgemeines Beispiel für Arten ohne eigenes: Werte je Basisfeld
GENERIC = {"title": "Example title", "publicationTitle": "Example publication", "publisher": "Example Publisher",
           "place": "London", "date": "2024", "pages": "1-10", "volume": "1", "number": "1", "url": "https://www.example.org"}

_lock = threading.Lock()
_memory: dict = {"schema": None, "at": 0.0}


def _cache_file():
    return paths.data_dir() / "csl-cache" / "zotero-schema.json"


def load_schema(client) -> tuple[dict | None, str]:
    """Schema aus Zotero (höchstens stündlich neu), sonst die zuletzt gespeicherte Fassung. Rückgabe (Schema, Quelle)."""
    with _lock:
        if _memory["schema"] and time.time() - _memory["at"] < SCHEMA_FRESH_SECONDS:
            return _memory["schema"], "zotero"
        try:
            if not client.is_available():
                raise ZoteroUnavailable("Zotero läuft nicht.")
            schema = client.schema()
            if not isinstance(schema, dict) or "itemTypes" not in schema:
                raise ZoteroError("Unerwartetes Schema")
            _memory.update(schema=schema, at=time.time())
            try:
                f = _cache_file()
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            except OSError as e:
                log.warning("Zotero-Schema nicht zwischengespeichert: %s", e)
            return schema, "zotero"
        except (ZoteroUnavailable, ZoteroError) as e:
            log.info("Zotero-Schema nicht abrufbar: %s", e)
        try:
            return json.loads(_cache_file().read_text(encoding="utf-8")), "cache"
        except (OSError, ValueError):
            return None, ""


def _date(value: str) -> dict:
    parts = [int(x) for x in re.findall(r"\d+", value)[:3]]
    return {"date-parts": [parts]} if parts else {"literal": value}


def to_csl(schema: dict, item: dict) -> dict:
    """Zotero-Eintrag → CSL-JSON nach den Zuordnungen im Zotero-Schema (wie Zotero.Utilities.Item.itemToCSLJSON)."""
    itype = item["itemType"]
    spec = next(t for t in schema["itemTypes"] if t["itemType"] == itype)
    csl = schema["csl"]
    values: dict[str, str] = {}
    for f in spec["fields"]:
        v = item.get(f["field"])
        if v:
            values[f["field"]] = v
            if f.get("baseField"):
                values.setdefault(f["baseField"], v)
    out: dict = {"type": next((c for c, zs in csl["types"].items() if itype in zs), "document")}
    for var, fields in csl["fields"]["text"].items():
        v = next((values[f] for f in fields if values.get(f)), None)
        if v:
            out[var] = v
    for var, field in csl["fields"]["date"].items():
        if values.get(field):
            out[var] = _date(values[field])
    # Die Hauptrolle der Art (Künstler:in, Erfinder:in …) gibt Zotero als „author“ weiter
    primary = next((c["creatorType"] for c in spec["creatorTypes"] if c.get("primary")), None)
    for c in item.get("creators") or []:
        var = csl["names"].get("author" if c["creatorType"] == primary else c["creatorType"])
        if var:
            name = {"literal": c["name"]} if "name" in c else {"family": c["lastName"], "given": c["firstName"]}
            out.setdefault(var, []).append(name)
    return out


def _generic(spec: dict) -> dict:
    item = {"itemType": spec["itemType"]}
    for f in spec["fields"]:
        value = GENERIC.get(f.get("baseField") or f["field"])
        if value:
            item[f["field"]] = value
    primary = next((c["creatorType"] for c in spec["creatorTypes"] if c.get("primary")), None)
    if primary:
        item["creators"] = [_p(primary, "Jane", "Doe")]
    return item


# Standardbeispiele der Vorschau → Eintragsart und Bedingung an die Personen (Anzahl Autor:innen, Herausgeber:innen)
LIBRARY_MATCH = {
    "book": ("book", lambda authors, editors: authors >= 1),
    "chapter": ("bookSection", None),
    "article": ("journalArticle", lambda authors, editors: 1 <= authors <= 3),
    "article4": ("journalArticle", lambda authors, editors: authors >= 4),
    "newspaper": ("newspaperArticle", None),
    "webpage": ("webpage", None),
    "thesis": ("thesis", None),
    "report": ("report", None),
    "edited": ("book", lambda authors, editors: authors == 0 and editors >= 1),
}


def pick_library_items(store, examples: list[str]) -> dict[str, tuple[str, str]]:
    """Je Beispiel (Standardbeispiel oder „z:<Eintragsart>“) der vollständigste passende Eintrag der Bibliothek –
    mit Jahr, Zeitschrift bzw. Buchtitel, DOI oder URL und möglichst mehreren Personen, bei Gleichstand der neueste."""
    out = {}
    for ex in examples:
        itype, cond = LIBRARY_MATCH.get(ex) or ((ex[2:], None) if ex.startswith("z:") else (None, None))
        if not itype:
            continue
        best, best_score = None, None
        for row in store.items_of_type(itype):
            creators = row["creators"]
            if cond and not cond(sum(c.get("creatorType") == "author" for c in creators),
                                 sum(c.get("creatorType") == "editor" for c in creators)):
                continue
            score = (bool(row["year"]), bool(row["publication"]), bool(row["doi"] or row["url"]), min(len(creators), 4),
                     row["updated_at"] or 0)
            if best_score is None or score > best_score:
                best, best_score = (row["lib"], row["key"]), score
        if best:
            out[ex] = best
    return out


def type_names(schema: dict | None, lang: str = "de") -> dict[str, str]:
    """Namen der Eintragsarten in der Sprache der Oberfläche (aus dem Zotero-Schema)."""
    locales = (schema or {}).get("locales") or {}
    return ((locales.get("de") if lang == "de" else None) or locales.get("en-US") or {}).get("itemTypes") or {}


def sample_types(schema: dict, lang: str = "de") -> list[dict]:
    """Alle Eintragsarten von Zotero ausser den Standardbeispielen: Name in der Sprache der Oberfläche und Beispiel."""
    names = type_names(schema, lang)
    out = []
    for spec in schema["itemTypes"]:
        itype = spec["itemType"]
        if itype in SKIP or itype in DEFAULT_TYPES:
            continue
        sample = SAMPLES.get(itype)
        item = {"itemType": itype, **{k: v for k, v in sample.items() if not k.startswith("_")}} if sample else _generic(spec)
        csl = to_csl(schema, item)
        csl["id"] = f"z:{itype}"
        if sample and sample.get("_locator"):
            csl["__locator"] = sample["_locator"]
        out.append({"type": itype, "label": names.get(itype) or itype, "item": csl})
    out.sort(key=lambda x: x["label"].casefold())
    return out
