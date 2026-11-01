"""KI-Vorschläge (Konzept 3.4 „KI-Vorauswahl“, 3.7 Punkt 5, 3.8): über den Port ``ChatModel``.

- Screening: je Stapel von etwa 20 Treffern ein Vorschlag „passend“, „nicht passend“ oder „Grenzfall“ mit einem Satz
  Begründung, dem betroffenen Kriterium und ggf. einem Zielordner. Ans Modell gehen nur Titel, Zeitschrift, Jahr und
  Abstract – nie Volltexte. Der Vorschlag ändert nichts am Stand: entscheiden tun Forschende.
- Datenbanken: aus Fragestellung, Beschreibung und Kriterien ein Vorschlag für Disziplinen und Datenbanken aus dem
  Katalog, je mit einem Satz Begründung. Übernommen wird nur, was die Nutzerin bzw. der Nutzer anklickt.
- Konzeptblöcke (Konzept 3.2): aus dem Projekttext Blöcke mit Suchbegriffen, MeSH und PsycInfo-Schlagwörtern. Auch
  das nur als Vorschlag; Schlagwörter müssen geprüft werden, weil Sprachmodelle Einträge erfinden können.

Antworten des Modells werden immer geprüft (unbekannte IDs, falsche Klassen, Datenbanken ausserhalb des Katalogs fallen
weg) – auch wenn der Adapter strukturierte Ausgaben nach Schema liefert.
"""

from __future__ import annotations

import json
import math
import re

from .export import MAX_FOLDERS
from .sources import catalog

LABELS = {"passend": "include", "nicht passend": "exclude", "grenzfall": "borderline"}
LABEL_TEXT = {"include": "passend", "exclude": "nicht passend", "borderline": "Grenzfall"}
BATCH = 20

SCREENING_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "string", "enum": list(LABELS)},
                    "folder": {"type": "integer", "enum": list(range(MAX_FOLDERS + 1))},
                    "criterion": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "label", "folder", "criterion", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _lines(text: str) -> list[str]:
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


def _bullets(text: str, empty: str = "–") -> list[str]:
    return [f"- {x}" for x in _lines(text)] or [f"- {empty}"]


def screening_system(project: dict) -> str:
    """Gleich für alle Stapel eines Projekts (gut für den Cache des Anbieters)."""
    folders = [f for f in project.get("folder_map") or [] if f.get("label") or f.get("path")]
    parts = [
        "Du unterstützt Forschende beim Screening von Literatur nach Titel und Abstract. Du schlägst nur vor; "
        "entscheiden tun die Forschenden. Antworte auf Deutsch.",
        "",
        f"Projekt: {project.get('title', '')}",
        f"Fragestellung: {project.get('question') or '–'}",
    ]
    if project.get("description"):
        parts.append(f"Kurzbeschreibung: {project['description']}")
    parts += ["", "Einschlusskriterien:", *_bullets(project.get("criteria_in"), "(keine angegeben)"),
              "", "Ausschlusskriterien:", *_bullets(project.get("criteria_out"), "(keine angegeben)")]
    if folders:
        parts += ["", "Zielordner (Themen) für passende Arbeiten:",
                  *[f"{f['slot']}: {f.get('label') or f.get('path')}" for f in folders]]
    parts += [
        "",
        "Ordne jeden Treffer einer Klasse zu:",
        "- „passend“: erfüllt die Einschlusskriterien, kein Ausschlusskriterium greift.",
        "- „nicht passend“: ein Ausschlusskriterium greift klar, oder das Thema der Fragestellung fehlt.",
        "- „grenzfall“: liegt an der Grenze eines Kriteriums – etwa wenn eine Arbeit gerade die Schwelle zwischen einem "
        "eingeschlossenen und einem ausgeschlossenen Phänomen untersucht – oder die Angaben reichen für ein Urteil nicht.",
        "Fehlt das Abstract, urteile nur nach dem Titel und wähle im Zweifel „grenzfall“.",
        "Gib je Treffer an: id (wie angegeben), label, folder (Nummer des passenden Zielordners aus der Liste, sonst 0), criterion (das "
        "Kriterium, auf das sich das Urteil stützt, kurz zitiert) und reason (genau ein Satz Begründung).",
        "Beurteile jeden Treffer der Liste genau einmal.",
    ]
    return "\n".join(parts)


def _item_block(it: dict) -> str:
    meta = ", ".join(str(x) for x in (it.get("journal"), it.get("year")) if x)
    abstract = (it.get("abstract") or "").strip()
    return "\n".join([
        f"id: {it['id']}",
        f"Titel: {it.get('title') or '(ohne Titel)'}",
        f"Erschienen: {meta or '–'}",
        f"Abstract: {abstract if len(abstract) >= 50 else '(kein Abstract – nur Titel)'}",
    ])


def screening_prompt(items: list[dict]) -> str:
    return f"Beurteile diese {len(items)} Treffer:\n\n" + "\n\n".join(_item_block(it) for it in items)


def parse_screening(result: object, ids: list[int], folder_slots: set[int]) -> list[dict]:
    """Antwort prüfen. Für jede angefragte ID genau ein Eintrag; fehlt eine, bleibt der Vorschlag leer."""
    raw = result.get("items") if isinstance(result, dict) else result if isinstance(result, list) else []
    by_id: dict[int, dict] = {}
    for x in raw or []:
        if not isinstance(x, dict):
            continue
        try:
            rid = int(x.get("id"))
        except (TypeError, ValueError):
            continue
        label = LABELS.get(str(x.get("label", "")).strip().lower())
        if rid not in ids or not label or rid in by_id:
            continue
        try:
            folder = int(x.get("folder") or 0)
        except (TypeError, ValueError):
            folder = 0
        by_id[rid] = {
            "id": rid, "label": label,
            "folder": folder if folder in folder_slots and label != "exclude" else None,
            "criterion": str(x.get("criterion") or "").strip()[:200],
            "reason": " ".join(str(x.get("reason") or "").split())[:400],
        }
    return [by_id.get(rid, {"id": rid, "label": "", "folder": None, "criterion": "", "reason": ""}) for rid in ids]


# ------------------------------------------------------------------------------------------- Datenbanken
def sources_schema() -> dict:
    allowed = [s["id"] for s in catalog.CATALOG if s["access"] != "never"]
    return {
        "type": "object",
        "properties": {
            "disciplines": {"type": "array", "items": {"type": "string", "enum": list(catalog.DISCIPLINES)}},
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string", "enum": allowed}, "reason": {"type": "string"}},
                    "required": ["id", "reason"],
                    "additionalProperties": False,
                },
            },
            "note": {"type": "string"},
        },
        "required": ["disciplines", "sources", "note"],
        "additionalProperties": False,
    }


def sources_system() -> str:
    rows = []
    for s in catalog.CATALOG:
        if s["access"] == "never":
            continue
        disc = ", ".join(catalog.DISCIPLINES[d] for d in s["disciplines"])
        rows.append(f"- {s['id']}: {s['label']} | {disc} | {catalog.ACCESS[s['access']]} | {s['note']}")
    disciplines = "\n".join(f"- {k}: {v}" for k, v in catalog.DISCIPLINES.items())
    return "\n".join([
        "Du berätst Forschende bei der Wahl von Literaturdatenbanken für eine systematische Recherche. Du schlägst nur "
        "vor; die Forschenden wählen. Antworte auf Deutsch.",
        "", "Disziplinen:", disciplines,
        "", "Datenbanken (id: Name | Disziplinen | Zugang | Hinweis):", *rows,
        "",
        "Wähle die Disziplinen, die die Fragestellung berührt, und die Datenbanken, die für eine gründliche Suche "
        "nötig sind – auch solche, die nur per RIS-Import gehen, wenn sie fachlich zentral sind. Nimm OpenAlex als "
        "breite Basis dazu. Begründe jede Datenbank mit genau einem Satz, bezogen auf die Fragestellung. In note höchstens "
        "zwei Sätze zu Lücken oder Besonderheiten (z. B. graue Literatur, Sprachen).",
    ])


def sources_prompt(project: dict) -> str:
    return "\n".join([
        f"Projekt: {project.get('title', '')}",
        f"Fragestellung: {project.get('question') or '–'}",
        f"Kurzbeschreibung: {project.get('description') or '–'}",
        "Einschlusskriterien:", *_bullets(project.get("criteria_in")),
        "Ausschlusskriterien:", *_bullets(project.get("criteria_out")),
    ])


def parse_sources(result: object) -> dict:
    result = result if isinstance(result, dict) else {}
    disciplines = [d for d in result.get("disciplines") or [] if d in catalog.DISCIPLINES]
    seen, sources = set(), []
    for x in result.get("sources") or []:
        sid = (x or {}).get("id") if isinstance(x, dict) else None
        entry = catalog.BY_ID.get(sid)
        if not entry or entry["access"] == "never" or sid in seen:
            continue
        seen.add(sid)
        sources.append({"id": sid, "label": entry["label"], "access": entry["access"], "in_app": entry["in_app"],
                        "reason": " ".join(str(x.get("reason") or "").split())[:400]})
    return {"disciplines": list(dict.fromkeys(disciplines)), "sources": sources,
            "note": " ".join(str(result.get("note") or "").split())[:500]}


# ------------------------------------------------------------------------------------------- Konzeptblöcke
BLOCKS_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["include", "exclude"]},
                    "field": {"type": "string", "enum": ["tiab", "ti"]},
                    "terms": {"type": "array", "items": {"type": "string"}},
                    "mesh": {"type": "array", "items": {"type": "string"}},
                    "psycinfo": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["name", "kind", "field", "terms", "mesh", "psycinfo", "reason"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["blocks", "note"],
    "additionalProperties": False,
}


def blocks_system() -> str:
    return "\n".join([
        "Du hilfst Forschenden, für eine systematische Literaturrecherche Konzeptblöcke zu bilden. Du schlägst nur vor; "
        "die Forschenden prüfen und wählen. Namen, Begründungen und Hinweise auf Deutsch.",
        "",
        "Ein Konzeptblock fasst gleichbedeutende Suchbegriffe für einen Teil der Fragestellung zusammen. Innerhalb eines "
        "Blocks gilt ODER, zwischen Blöcken UND; Ausschlussblöcke kommen mit NOT dazu.",
        "",
        "Regeln:",
        "- 2 bis 4 Einschlussblöcke (kind \"include\"), typisch Population, Phänomen, Kontext. Nur Blöcke, die die "
        "Fragestellung verlangt – jeder weitere Block mit UND verkleinert die Treffermenge.",
        "- Suchbegriffe auf Englisch, der Sprache der Datenbanken. Deutsche Begriffe nur, wenn die Fragestellung "
        "ausdrücklich deutschsprachige Literatur verlangt.",
        "- Je Block 5 bis 25 Begriffe: Synonyme, Schreibvarianten (cyberbullying, cyber-bullying), Fach- und "
        "Alltagsbegriffe. * für beliebige Endung, wo sinnvoll (adolescen*), mit mindestens vier Buchstaben vor dem *. "
        "Phrasen aus mehreren Wörtern ohne Anführungszeichen.",
        "- field: \"tiab\" (Titel und Abstract) als Normalfall.",
        "- mesh: MeSH-Deskriptoren für PubMed; psycinfo: Schlagwörter des APA-Thesaurus für PsycInfo. Nur Einträge, "
        "die es sicher gibt, in exakter Schreibweise; im Zweifel leer lassen.",
        "- Ausschlussblock (kind \"exclude\", field \"ti\") nur, wenn ein Ausschlusskriterium eindeutig an Begriffen im "
        "Titel erkennbar ist (z. B. Tierstudien). Im Zweifel keinen: Was mit NOT wegfällt, sieht niemand mehr; "
        "Abgrenzungen gehören in die Vorfilter der App, die nur markieren.",
        "- Gibt es schon Blöcke, verwende für dasselbe Konzept denselben Namen und schlage dort fehlende Begriffe vor.",
        "- reason: ein Satz, wofür der Block steht. note: höchstens zwei Sätze zu Lücken oder Risiken der Strategie.",
    ])


def blocks_prompt(project: dict, existing: list[dict] | None = None) -> str:
    lines = [
        f"Projekt: {project.get('title', '')}",
        f"Fragestellung: {project.get('question') or '–'}",
        f"Kurzbeschreibung: {project.get('description') or '–'}",
        "Einschlusskriterien:", *_bullets(project.get("criteria_in")),
        "Ausschlusskriterien:", *_bullets(project.get("criteria_out")),
    ]
    usable = [b for b in existing or [] if b.get("terms") or b.get("mesh") or b.get("psycinfo")]
    if usable:
        lines += ["", "Vorhandene Blöcke:"]
        for b in usable:
            kind = "Ausschluss" if b.get("kind") == "exclude" else "Einschluss"
            lines.append(f"- {b.get('name') or '(ohne Name)'} ({kind}): " + "; ".join(b.get("terms") or [])
                         + (f" | MeSH: {'; '.join(b['mesh'])}" if b.get("mesh") else "")
                         + (f" | PsycInfo: {'; '.join(b['psycinfo'])}" if b.get("psycinfo") else ""))
    return "\n".join(lines)


def blocks_focus(focus: dict) -> str:
    """Nur einen Block neu vorschlagen lassen (die Forschenden haben den bisherigen Vorschlag verworfen)."""
    kind = "Ausschluss" if focus.get("kind") == "exclude" else "Einschluss"
    lines = ["", f"Schlage nur den Block „{focus.get('name', '')}“ ({kind}) neu vor und gib genau diesen einen Block zurück, "
             "mit demselben Namen."]
    if focus.get("terms"):
        lines.append("Bisheriger Vorschlag, den die Forschenden nicht übernehmen wollten: " + "; ".join(focus["terms"]))
    if (focus.get("hint") or "").strip():
        lines.append(f"Wunsch der Forschenden: {focus['hint'].strip()}")
    return "\n".join(lines)


def _clean_list(values: object, limit: int) -> list[str]:
    out, seen = [], set()
    for v in values if isinstance(values, list) else []:
        v = " ".join(str(v or "").replace('"', " ").split())[:80]
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out[:limit]


def parse_blocks(result: object) -> dict:
    result = result if isinstance(result, dict) else {}
    blocks, names = [], set()
    for x in result.get("blocks") or []:
        if not isinstance(x, dict):
            continue
        name = " ".join(str(x.get("name") or "").split())[:60]
        terms, mesh, psycinfo = _clean_list(x.get("terms"), 40), _clean_list(x.get("mesh"), 15), _clean_list(x.get("psycinfo"), 15)
        if not name or not (terms or mesh or psycinfo) or name.lower() in names:
            continue
        names.add(name.lower())
        kind = "exclude" if x.get("kind") == "exclude" else "include"
        blocks.append({"name": name, "kind": kind, "field": "ti" if kind == "exclude" or x.get("field") == "ti" else "tiab",
                       "terms": terms, "mesh": mesh, "psycinfo": psycinfo,
                       "reason": " ".join(str(x.get("reason") or "").split())[:300]})
    return {"blocks": blocks[:6], "note": " ".join(str(result.get("note") or "").split())[:500]}


# ------------------------------------------------------------------------------------------- Ordner (Untersammlungen)
FOLDERS_SCHEMA = {
    "type": "object",
    "properties": {
        "folders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["folders", "note"],
    "additionalProperties": False,
}


def folders_system() -> str:
    return "\n".join([
        "Du hilfst Forschenden, die Literatur einer Recherche in Zotero thematisch zu ordnen. Du schlägst nur vor; die "
        "Forschenden wählen, und angelegt wird erst nach ihrer Bestätigung. Antworte auf Deutsch.",
        "",
        "Schlage 3 bis 6 Ordner (Untersammlungen) vor, in die die aufgenommene Literatur beim Screening sortiert wird:",
        "- je ein kurzer Name (1 bis 4 Wörter, ohne Schrägstrich, ohne Nummer) und ein Satz, was hineingehört;",
        "- die Ordner sollen sich gegenseitig ausschliessen und zusammen die Fragestellung abdecken (z. B. Phänomene, "
        "Rollen, Bewältigung, Prävention);",
        "- keine Namen, die es unter der Sammlung schon gibt; vorhandene Ordner-Zuordnungen berücksichtigen;",
        "- sind schon Titel aufgenommener Arbeiten angegeben, richte die Ordner danach aus.",
        "In note höchstens ein Satz, falls die Gliederung eine Schwäche hat.",
    ])


def folders_prompt(project: dict, parent: str, existing_children: list[str], titles: list[str]) -> str:
    current = [f"{f['slot']}: {f.get('label') or f.get('path')}" for f in project.get("folder_map") or []
               if f.get("label") or f.get("path")]
    lines = [
        f"Projekt: {project.get('title', '')}",
        f"Fragestellung: {project.get('question') or '–'}",
        f"Kurzbeschreibung: {project.get('description') or '–'}",
        "Einschlusskriterien:", *_bullets(project.get("criteria_in")),
        f"Übergeordnete Sammlung in Zotero: {parent or '(oberste Ebene)'}",
        "Schon vorhandene Untersammlungen dort:", *(f"- {x}" for x in existing_children or ["(keine)"]),
        "Bisherige Ordner-Zuordnung:", *(f"- {x}" for x in current or ["(keine)"]),
    ]
    if titles:
        lines += ["", f"Titel bereits aufgenommener Arbeiten ({len(titles)}):", *(f"- {x}" for x in titles)]
    return "\n".join(lines)


def parse_folders(result: object, existing_children: list[str]) -> dict:
    result = result if isinstance(result, dict) else {}
    taken = {x.lower() for x in existing_children}
    out = []
    for x in result.get("folders") or []:
        if not isinstance(x, dict):
            continue
        name = " ".join(str(x.get("name") or "").replace("/", " ").split()).strip(" .-–")[:60]
        if not name or name.lower() in taken:
            continue
        taken.add(name.lower())
        out.append({"name": name, "description": " ".join(str(x.get("description") or "").split())[:300]})
    return {"folders": out[:6], "note": " ".join(str(result.get("note") or "").split())[:300]}


# ------------------------------------------------------------------------------------------- Bericht
REPORT_SCHEMA = {
    "type": "object",
    "properties": {"methods": {"type": "string"}, "results": {"type": "string"}, "note": {"type": "string"}},
    "required": ["methods", "results", "note"],
    "additionalProperties": False,
}


def report_system(language: str) -> str:
    return "\n".join([
        "Du formulierst aus den Angaben eines Suchprotokolls zwei Textteile für den Methodenteil einer Arbeit. Du erfindest "
        f"nichts. Schreibe auf {language}, sachlich, in Absätzen ohne Überschriften.",
        "",
        "methods: Informationsquellen mit Datum der letzten Suche, Suchstrategie (Aufbau; die vollständigen Suchstrings stehen "
        "im Anhang), Ein- und Ausschlusskriterien, Auswahlprozess (wie viele Personen, unabhängig oder nicht, Umgang mit "
        "Uneinigkeit, eingesetzte Hilfsmittel wie Vorfilter und Sprachmodell).",
        "results: Ablauf der Auswahl von den gefundenen Datensätzen bis zu den eingeschlossenen Arbeiten, mit den Zahlen und "
        "den Ausschlussgründen.",
        "",
        "Regeln:",
        "- Nur was in den Angaben steht. Keine Zahl, kein Datum, keine Datenbank und kein Werkzeug ergänzen; nichts ausrechnen.",
        "- Fehlt etwas, das in einen solchen Bericht gehört, schreibe an der Stelle [fehlt: …], statt es zu erraten.",
        "- Keine Behauptung, die Arbeit folge PRISMA oder sei ein systematischer Review. Keine Wertung der Qualität.",
        "- Steht in den Angaben, dass nur eine Person je Treffer entschieden hat, sage das ausdrücklich; schreibe nie „unabhängig“, "
        "wenn es dort nicht steht.",
        "- Sprachmodell-Vorschläge als Vorschläge benennen; entschieden haben die Forschenden.",
        "- Endet die Auswahl beim Titel-/Abstract-Screening, sage das; beschreibe keine Volltextprüfung.",
        "note: höchstens zwei Sätze zu Lücken in den Angaben, sonst leer.",
    ])


NUMBER = re.compile(r"\d{1,3}(?:['’ ,.]\d{3})+(?!\d)|\d+")


def numbers_in(text: str) -> set[str]:
    """Zahlen eines Textes, Tausendertrennzeichen entfernt („1 250“ und „1250“ gelten als dieselbe Zahl)."""
    return {re.sub(r"\D", "", m.group()) for m in NUMBER.finditer(text or "")}


def parse_report(result: object, facts: str) -> dict:
    """Antwort prüfen: Zahlen, die nicht in den Fakten stehen, werden gemeldet (nicht still entfernt)."""
    result = result if isinstance(result, dict) else {}
    methods, results = str(result.get("methods") or "").strip(), str(result.get("results") or "").strip()
    unknown = sorted(numbers_in(f"{methods} {results}") - numbers_in(facts), key=lambda x: (len(x), x))
    return {"methods": methods, "results": results, "note": " ".join(str(result.get("note") or "").split())[:500],
            "warnings": unknown}


# ------------------------------------------------------------------------------------------- Token (Schätzung)
# Vor dem Aufruf geschätzt aus der Textlänge: deutsche Anweisungen etwa 3,8 Zeichen je Token, Titel und Abstracts (meist
# Englisch) etwa 4,5 – abgeglichen am 29.10.2026 mit einem echten Gemini-Lauf (20 Treffer: 7'948 Token, Schätzung etwas
# darüber). Die Anbieter zählen leicht verschieden. Hinaus: Erfahrungswerte bei Aufwand „low“, Denken eingerechnet.
CHARS_PER_TOKEN = 3.8
CHARS_PER_TOKEN_TEXT = 4.5
OUT_PER_RECORD = 90
OUT_EST = {"sources": 450, "blocks": 1500, "folders": 350, "report": 900}


def tokens(text: str, chars_per_token: float = CHARS_PER_TOKEN) -> int:
    return max(1, math.ceil(len(text or "") / chars_per_token))


def schema_tokens(schema: dict) -> int:
    return tokens(json.dumps(schema, ensure_ascii=False))


def item_tokens(it: dict) -> int:
    """Ein Treffer im Screening-Prompt (Titel, Angaben, Abstract)."""
    return tokens(_item_block(it), CHARS_PER_TOKEN_TEXT) + 2


def screening_system_tokens(project: dict) -> int:
    """Je Stapel: Systemtext, Schema und Kopfzeile."""
    return tokens(screening_system(project)) + schema_tokens(SCREENING_SCHEMA) + 10


def used(model: str, usage: dict) -> dict:
    """Verbrauch einheitlich: Input (mit zwischengespeicherten Token), Output, davon aus dem Cache, Kosten (falls Preis bekannt)."""
    cached = usage.get("cache_read_input_tokens", 0)
    return {"input": usage.get("input_tokens", 0) + cached + usage.get("cache_creation_input_tokens", 0),
            "output": usage.get("output_tokens", 0), "cached": cached, "requests": usage.get("requests", 0),
            "cost": estimate_cost(model, usage)}


def estimate(model: str, input_tokens: int, output_tokens: int) -> dict:
    return {"input": input_tokens, "output": output_tokens,
            "cost": estimate_cost(model, {"input_tokens": input_tokens, "output_tokens": output_tokens})}


# ------------------------------------------------------------------------------------------- Kosten (Richtwert)
# USD je 1 Mio. Token (Anthropic-Preisliste, Stand Oktober 2026); unbekanntes Modell → keine Kostenangabe
# Richtwert je Treffer: Titel, Angaben und Abstract (~380 Token) hinein, ein Eintrag mit Begründung (~90) hinaus
PER_RECORD = {"input_tokens": 380, "output_tokens": OUT_PER_RECORD}
PRICES = {"claude-opus-5-5": (4.0, 20.0, 0.2), "claude-sonnet-5-5": (2.0, 10.0, 0.2), "claude-haiku-5-5": (0.1, 0.5, 0.01)}


def estimate_cost(model: str, usage: dict) -> float | None:
    p = PRICES.get(model)
    if not p or not usage:
        return None
    inp, out, cache = p
    return round((usage.get("input_tokens", 0) * inp + usage.get("output_tokens", 0) * out
                  + usage.get("cache_read_input_tokens", 0) * cache
                  + usage.get("cache_creation_input_tokens", 0) * inp * 1.25) / 1e6, 4)
