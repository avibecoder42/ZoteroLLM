"""Pool: alle Treffer eines Projekts ohne Duplikate, mit sichtbaren und abschaltbaren Vorfiltern (Konzept 3.7).

Grundsatz: Keine Regel entfernt einen Treffer. Regeln setzen ein Kennzeichen mit Grund; entscheiden tut der Mensch.

Vorfilter (je Projekt gespeichert, Liste von dicts mit ``active``):
- ``{"kind": "title", "pattern": "bully* OR mobbing", "exceptions": "banter, teasing", "exception_scope": "text"}``
  Titel enthält einen der Begriffe. ``bully*`` findet die Zeichenfolge auch mitten im Wort und in der Mehrzahl
  (Cyberbullying, Cyberbullies); ohne ``*`` gilt nur das ganze Wort. Kommt ein Ausnahmebegriff vor (im Titel oder,
  mit ``exception_scope = "text"``, auch im Abstract), wird der Treffer nicht ausgeblendet, sondern ein **Grenzfall**.
- ``{"kind": "text", "pattern": "…"}``                     Titel oder Abstract enthält … (Ausnahmen wie oben)
- ``{"kind": "journal", "pattern": "…"}``                  Zeitschrift enthält …
- ``{"kind": "type", "allowed": ["journalArticle"]}``      andere Publikationsart
- ``{"kind": "no_abstract"}``                              ohne Abstract (standardmässig aus)
- ``{"kind": "language", "allowed": ["en", "de"]}``        andere Sprache (unbekannte Sprache bleibt sichtbar)
- ``{"kind": "year_min", "value": 2006}``                  erschienen vor …
- ``{"kind": "in_zotero"}``                                schon in der Zotero-Zielbibliothek

Ausgeblendete lassen sich prüfen (``review``): „restore“ holt zurück, „borderline“ macht einen Grenzfall daraus,
„exclude“ bestätigt den Ausschluss.
"""

from __future__ import annotations

import re
import uuid

DEFAULT_PREFILTERS = [
    {"kind": "in_zotero", "active": True},
    {"kind": "no_abstract", "active": False},
    {"kind": "language", "allowed": ["en", "de"], "active": False},
]
PATTERN_KINDS = ("title", "text", "journal")
TYPE_LABELS = {"journalArticle": "Zeitschriftenartikel", "book": "Buch", "bookSection": "Buchkapitel",
               "conferencePaper": "Konferenzbeitrag", "thesis": "Hochschulschrift", "report": "Bericht",
               "preprint": "Preprint"}
MIN_ABSTRACT = 50
# Stärke eines Grenzfalls (Reihenfolge der Warteschlange): von Hand gekennzeichnet, Ausnahme im Titel, im Abstract
STRENGTH = {"human": 3, "title": 2, "abstract": 1, "ai": 1}


def prefilter_label(f: dict) -> str:
    k = f.get("kind")
    if k == "title":
        label = f"Titel enthält {f.get('pattern', '')}"
    elif k == "text":
        label = f"Titel/Abstract enthält {f.get('pattern', '')}"
    elif k == "journal":
        label = f"Zeitschrift enthält {f.get('pattern', '')}"
    elif k == "type":
        label = "andere Art als " + ", ".join(TYPE_LABELS.get(t, t) for t in f.get("allowed") or [])
    elif k == "no_abstract":
        label = "ohne Abstract"
    elif k == "language":
        label = "Sprache nicht " + "/".join(f.get("allowed") or [])
    elif k == "year_min":
        label = f"erschienen vor {f.get('value')}"
    elif k == "in_zotero":
        label = "schon in Zotero"
    else:
        label = k or "?"
    if k in PATTERN_KINDS and (f.get("exceptions") or "").strip():
        label += " (mit Ausnahmen)"
    return label


def with_ids(prefilters: list[dict]) -> list[dict]:
    out = []
    for f in prefilters or []:
        f = dict(f)
        f.setdefault("id", uuid.uuid4().hex[:8])
        f.setdefault("active", True)
        if f.get("kind") in PATTERN_KINDS:
            f.setdefault("exceptions", "")
            f.setdefault("exception_scope", "text")
        f["label"] = prefilter_label(f)
        out.append(f)
    return out


def split_terms(pattern: str) -> list[str]:
    return [t.strip().strip('"').strip() for t in re.split(r"\s+OR\s+|[,;\n]", pattern or "", flags=re.I) if t.strip()]


def _term_regex(term: str) -> str:
    wild = term.endswith("*")
    core = term.rstrip("*")
    if wild and core.endswith("y"):
        core = core[:-1] + "(y|ie)"  # bully* → bullies, Cyberbullies
    rx = re.escape(core)
    rx = rx.replace(r"\(", "(?:").replace(r"\)", ")").replace(r"\|", "|")  # (y|ie) bleibt eine Gruppe
    rx = rx.replace(r"\ ", r"\s+").replace(r"\-", r"[-\s]?")  # cyber-bully = cyber bully = cyberbully
    return rf"(?:{rx})\w*" if wild else rf"\b(?:{rx})\b"


def pattern_regex(pattern: str) -> re.Pattern | None:
    """„bully* OR mobbing, cyber-bully*“ → Regex, Gross-/Kleinschreibung egal. Mit * auch mitten im Wort und
    in der Mehrzahl auf -ies; ``(y|ie)`` schreibt Wortformen ausdrücklich."""
    terms = split_terms(pattern)
    if not terms:
        return None
    try:
        return re.compile("|".join(_term_regex(t) for t in terms), re.I)
    except re.error:
        return re.compile("|".join(re.escape(t) for t in terms), re.I)


def matches(f: dict, rec: dict) -> bool:
    k = f.get("kind")
    if k in PATTERN_KINDS:
        rx = pattern_regex(f.get("pattern", ""))
        text = {"title": rec.get("title", ""), "journal": rec.get("journal", ""),
                "text": f"{rec.get('title', '')} {rec.get('abstract', '')}"}[k]
        return bool(rx and rx.search(text or ""))
    if k == "type":
        t = rec.get("type") or ""
        return bool(t) and t not in (f.get("allowed") or [])
    if k == "no_abstract":
        return len((rec.get("abstract") or "").strip()) < MIN_ABSTRACT
    if k == "language":
        lang = (rec.get("lang") or "").lower()
        return bool(lang) and lang not in [a.lower() for a in f.get("allowed") or []]
    if k == "year_min":
        return bool(rec.get("year")) and int(rec["year"]) < int(f.get("value") or 0)
    if k == "in_zotero":
        return bool(rec.get("zotero_key"))
    return False


def exception_hit(f: dict, rec: dict) -> dict | None:
    """Ausnahme einer Regel: {"term": gefundenes Wort, "where": "title" | "abstract"} oder None."""
    if f.get("kind") not in ("title", "text") or not (f.get("exceptions") or "").strip():
        return None
    rx = pattern_regex(f["exceptions"])
    if not rx:
        return None
    m = rx.search(rec.get("title") or "")
    if m:
        return {"term": m.group(0), "where": "title"}
    if f.get("exception_scope", "text") == "text":
        m = rx.search(rec.get("abstract") or "")
        if m:
            return {"term": m.group(0), "where": "abstract"}
    return None


def evaluate(prefilters: list[dict], rec: dict, reviews: dict[str, str] | None = None) -> dict:
    """Welche aktiven Regeln treffen, welche blenden aus, wo ist es ein Grenzfall?"""
    reviews = reviews or {}
    matched, hidden, borderline = [], [], []
    for f in prefilters:
        if not f.get("active") or not matches(f, rec):
            continue
        matched.append(f["id"])
        exc = exception_hit(f, rec)
        if exc:
            borderline.append({"rule": f["id"], "label": f.get("label") or prefilter_label(f), **exc,
                               "strength": STRENGTH[exc["where"]]})
        elif reviews.get(f["id"]) in ("restore", "borderline"):
            continue  # geprüft und zurückgeholt
        elif f.get("kind") == "in_zotero" and reviews.get(f["id"]) != "exclude" and (rec.get("decision") or {}).get("status", "open") != "open":
            continue  # selbst gesichtet: Oft ist der Treffer erst durch die Übergabe in Zotero
        else:
            hidden.append(f["id"])
    return {"matched": matched, "hidden": hidden, "borderline": borderline}


def _hits(rec: dict) -> list[dict]:
    """Fundstellen aus aktuellen Läufen; ist der Treffer nur noch aus früheren bekannt, diese."""
    found = rec.get("found") or []
    return [h for h in found if h.get("current", True)] or found


def sources_of(rec: dict) -> list[str]:
    return sorted({h["source"] for h in _hits(rec)})


def queries_of(rec: dict) -> list[str]:
    seen = []
    for h in _hits(rec):
        if h["query"] and h["query"] not in seen:
            seen.append(h["query"])
    return seen


def summarize(rec: dict, prefilters: list[dict], reviews: dict[str, str] | None = None) -> dict:
    """Kompakte Form für Liste und Screening."""
    data = rec.get("data") or {}
    ev = evaluate(prefilters, rec, reviews)
    decision = rec.get("decision")
    borderline = list(ev["borderline"])
    if decision and decision.get("borderline"):
        borderline.insert(0, {"rule": None, "label": "von Hand", "term": "", "where": "human",
                              "reason": decision.get("borderline_reason") or "", "strength": STRENGTH["human"]})
    ai = rec.get("ai") or None
    if ai and ai.get("label") == "borderline":
        borderline.append({"rule": None, "label": "KI", "term": "", "where": "ai", "reason": ai.get("reason") or "",
                           "strength": STRENGTH["ai"]})
    return {
        "id": rec["id"],
        "title": rec.get("title", ""),
        "authors": rec.get("authors") or [],
        "year": rec.get("year"),
        "journal": rec.get("journal", ""),
        "abstract": rec.get("abstract", ""),
        "abstract_source": data.get("abstract_source", ""),
        "no_abstract": len((rec.get("abstract") or "").strip()) < MIN_ABSTRACT,
        "doi": rec.get("doi", ""),
        "pmid": rec.get("pmid", ""),
        "openalex_id": rec.get("openalex_id", ""),
        "lang": rec.get("lang", ""),
        "type": rec.get("type", ""),
        "subjects": rec.get("subjects") or [],
        "cited_by": data.get("cited_by"),
        "url": data.get("url", ""),
        "sources": sources_of(rec),
        "queries": queries_of(rec),
        "zotero_key": rec.get("zotero_key", ""),
        "zotero_lib": rec.get("zotero_lib", ""),
        "stale": not rec.get("current", True),  # nur aus früheren Suchen oder gelöschten Suchstrings, schon entschieden
        "decision": decision,
        "ai": ai if ai and ai.get("label") else None,
        "hidden_by": ev["hidden"],
        "matched_by": ev["matched"],
        "borderline": borderline,
        "borderline_strength": max((b["strength"] for b in borderline), default=0),
        "reviews": reviews or {},
    }


def filter_pool(items: list[dict], *, source: str = "", query: str = "", year_from: int | None = None,
                year_to: int | None = None, journal: str = "", lang: str = "", text: str = "", status: str = "",
                show_hidden: bool = False, rule: str = "") -> list[dict]:
    """status: open | include | exclude | maybe | borderline | hidden | ai_include | ai_exclude | ai_borderline |
    ai_none. rule: nur Treffer dieser Regel."""
    rx = pattern_regex(text) if text else None
    out = []
    for it in items:
        if status == "hidden":
            if not it["hidden_by"]:
                continue
        elif not show_hidden and it["hidden_by"]:
            continue
        if rule and rule not in it["matched_by"]:
            continue
        if source and source not in it["sources"]:
            continue
        if query and query not in it["queries"]:
            continue
        if year_from and (not it["year"] or it["year"] < year_from):
            continue
        if year_to and (not it["year"] or it["year"] > year_to):
            continue
        if journal and journal.lower() not in (it["journal"] or "").lower():
            continue
        if lang and (it["lang"] or "").lower() != lang.lower():
            continue
        if rx and not rx.search(f"{it['title']} {it['abstract']}"):
            continue
        if status == "borderline" and not it["borderline"]:
            continue
        if status in ("open", "include", "exclude", "maybe") and status_of(it) != status:
            continue
        if status.startswith("ai_") and ((it.get("ai") or {}).get("label") or "none") != status[3:]:
            continue
        out.append(it)
    return out


def status_of(it: dict) -> str:
    d = it.get("decision")
    return d["status"] if d else "open"
