"""Forschungsstand in vier Schritten (siehe Konzept):

1. Relevante Texte finden: viele Suchanfragen (DE/EN), Treffer je Dokument zählen,
   Vorauswahl anhand der Abstracts – danach Pause zur Bestätigung (optional als
   Zotero-Sammlung, in der ergänzt werden kann).
2. Jeden Text einzeln auswerten: Auswertungsblatt je Dokument (ganzer Text oder die
   relevanten Teile), gespeichert im Index und als Notiz am Zotero-Eintrag.
3. Synthese: Gliederung aus allen Blättern, dann abschnittsweise schreiben.
4. Kontrolle: Belege und wörtliche Zitate gegen Blätter und Originaltext prüfen.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
import unicodedata
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from zotivity.engine import Engine
from zotivity.extract.chunker import estimate_tokens
from zotivity.i18n import tr
from zotivity.index.store import SearchFilter, strip_bidi
from zotivity.jobs import Job
from zotivity.llm import (ChatMessage, ChatModel, GenParams, LLMError, helper_model, main_model,
                           retry_after_truncation, truncation)
from zotivity.rag.markdown import latex_to_text, md_to_html
from zotivity.rag.prompts import LANG_NAMES
from zotivity.rag.sources import _merge_overlapping, author_year
from zotivity.retrieval import Searcher
from zotivity.zotero import ZoteroAuthRequired, ZoteroError, opens_in_reader, zotero_open_pdf_url, zotero_select_url

log = logging.getLogger(__name__)

SHEET_VERSION = 1

SHEET_SYSTEM = """Du erstellst Auswertungsblätter (Exzerpte) zu wissenschaftlichen Texten für einen späteren Forschungsstand.
Regeln:
- Nur Angaben, die im Text stehen. Fehlt etwas, schreibe "nicht angegeben".
- Seitenangaben stehen im Text als Markierungen [S. x] (gedruckte Seitenzahl) bzw. [o. S.] (Seite ohne Seitenzahl). Gib bei Zitaten die Seite der davor stehenden Markierung an, bei [o. S.] „o. S.“.
- Kernzitate müssen wörtlich und exakt aus dem Text stammen (Originalsprache), höchstens 3 Sätze je Zitat.
- Beschreibe Befunde präzise (Richtung, Grösse, Gruppen), ohne zu werten.
- {language_rule} Zitate bleiben in der Originalsprache.
- Antworte nur mit JSON."""

SHEET_SCHEMA = """{
  "kurzbeschreibung": "2–3 Sätze: Worum geht es?",
  "textsorte": "z. B. empirische Studie, Review, Theoriebeitrag, Bericht, Buch",
  "fragestellung": "...",
  "theorie": "theoretischer Rahmen, zentrale Konzepte",
  "methode": "Design, Erhebung, Auswertung",
  "stichprobe": "Grösse, Alter, Merkmale",
  "land_kontext": "...",
  "zeitraum": "Erhebungszeitraum",
  "zentrale_befunde": ["...", "..."],
  "grenzen": "Limitationen laut Text",
  "kernzitate": [{"zitat": "...", "seite": "12"}],
  "stichworte": ["...", "..."]
}"""

REVIEW_QUERY_PROMPT = """Forschungsfrage für einen Forschungsstand: {question}

Formuliere {n} Suchanfragen, um in einer Bibliothek mit deutsch- und englischsprachiger Fachliteratur möglichst ALLE relevanten Texte zu finden. Das Feld ist jung und die Begriffe variieren stark: decke Synonyme, verwandte Konzepte, Zielgruppen-Bezeichnungen, Technologien/Produktnamen und Fachtermini in beiden Sprachen ab (z. B. für Jugendliche: adolescents, youth, teenagers, young people, Heranwachsende). Mische kurze Stichwortanfragen und ausformulierte Anfragen. Jede Anfrage wird einzeln als Bedeutungs- und Stichwortsuche ausgeführt – keine Booleschen Operatoren (AND/OR).
{title_rule}
JSON-Format: {{"title": "...", "queries": ["...", "..."]}}"""

TITLE_RULE = "Gib ausserdem einen kurzen, treffenden Titel für den Forschungsstand an (höchstens 8 Wörter, Sprache der Frage).\n"

SCREEN_SYSTEM = "Du prüfst für einen Forschungsstand, welche Texte zur Forschungsfrage gehören. Sei inklusiv bei Grenzfällen (maybe), aber schliesse thematisch fremde Texte aus. Antworte nur mit JSON."

SCREEN_PROMPT = """Forschungsfrage: {question}

Texte:
{docs}

Entscheide für jeden Text: "include" (behandelt die Fragestellung direkt), "maybe" (teilweise/indirekt relevant) oder "exclude". Begründe kurz (ein Satz).

JSON-Format: {{"decisions": [{{"key": "ABCD1234", "decision": "include", "reason": "..."}}]}}"""

OUTLINE_SYSTEM = "Du planst einen wissenschaftlichen Forschungsstand. Antworte nur mit JSON."

OUTLINE_PROMPT = """Forschungsfrage: {question}
Ziel-Länge: etwa {words} Wörter, Sprache: {language}.

Auswertungsblätter der {n} einbezogenen Texte (Schlüssel in eckigen Klammern):
{sheets}

Entwirf eine Gliederung: Einleitung (Gegenstand, Relevanz, Vorgehen), thematische Abschnitte entlang von Befunden, Kontroversen und Methoden (nicht Text für Text!), und ein Schluss mit Forschungslücken. Ordne jedem Abschnitt die Schlüssel der Texte zu, die er hauptsächlich nutzt, und eine Wortzahl (Summe ≈ {words}).

JSON-Format: {{"title": "...", "sections": [{{"heading": "...", "focus": "was der Abschnitt leisten soll", "keys": ["ABCD1234"], "words": 600}}]}}"""

WRITE_SYSTEM = """Du schreibst einen wissenschaftlichen Forschungsstand auf Grundlage von Auswertungsblättern aus der Literaturbibliothek der Nutzerin bzw. des Nutzers.

Regeln:
- Verwende ausschliesslich Informationen aus den Auswertungsblättern. Nichts erfinden, keine externen Studien.
- Belege jede inhaltliche Aussage mit dem Schlüssel des Textes im Format [@SCHLÜSSEL] oder mit Seite [@SCHLÜSSEL, S. 12]. Mehrere Belege: [@KEY1; @KEY2].
- Wörtliche Zitate nur aus den "kernzitate" der Blätter, exakt und mit deren Seitenangabe. Steht dort als Seite „o. S.“ (Quelle ohne Seitenzahlen), belege mit [@SCHLÜSSEL, o. S.].
- Nennst du Autorinnen oder Autoren im Satz, setze den Beleg direkt dahinter: „Shin et al. [@SCHLÜSSEL] zeigen …“ (der Beleg nennt dann nur Jahr und Seite).
- Synthetisiere: vergleiche, gruppiere, benenne Widersprüche und methodische Unterschiede, statt Studien nacheinander nachzuerzählen.
- Kein LaTeX und keine Formelschreibweise (kein $…$, kein \\beta, \\ge, \\text): Kennwerte als normaler Text mit Unicode-Zeichen, z. B. β = .35, r = −.14, N = 7 450, ≥ 21, I² = 63 %.
- Wissenschaftlicher, sachlicher Stil. Markdown. Schreibe nur den angeforderten Abschnitt mit seiner Überschrift (##).

Auswertungsblätter (Schlüssel in eckigen Klammern):
{sheets}"""

WRITE_PROMPT = """Forschungsfrage: {question}
Sprache: {language}

Gliederung des Gesamttextes:
{outline}

Bisher geschriebene Abschnitte:
{previous}

Schreibe jetzt den Abschnitt „{heading}“ (Fokus: {focus}). Stütze dich vor allem auf: {keys}.
Umfang: {low}–{words} Wörter, Überschrift und Belege eingerechnet.{budget} Die Obergrenze ist verbindlich: Schreibe knapp und dicht, fasse ähnliche Befunde zusammen, statt jeden einzeln nachzuerzählen."""

SHORTEN_SYSTEM = """Du kürzt einen Abschnitt eines wissenschaftlichen Forschungsstands auf eine vorgegebene Länge.

Regeln:
- Nichts Neues hinzufügen: nur straffen, zusammenfassen und Nebensächliches streichen.
- Belege [@SCHLÜSSEL] bzw. [@SCHLÜSSEL, S. 12] unverändert übernehmen; jede verbleibende Aussage behält ihren Beleg.
- Wörtliche Zitate entweder exakt übernehmen oder ganz streichen – nie verändern.
- Überschrift (##), Sprache, Stil und Markdown beibehalten. Kein LaTeX.
- Antworte nur mit dem gekürzten Abschnitt."""

SHORTEN_PROMPT = """Kürze diesen Abschnitt von {words} auf höchstens {limit} Wörter (Überschrift und Belege eingerechnet). Behalte die zentralen Befunde, Vergleiche und Widersprüche; streiche Wiederholungen, Einzelheiten und Überleitungen.

{text}"""

LONG_FACTOR = 1.2  # ab 20 % über dem Plan gilt ein Abschnitt als zu lang


def count_words(text: str) -> int:
    """Wörter wie in der Anzeige: Überschrift und Belege zählen mit, Literaturverzeichnis und Anhang nicht."""
    return len((text or "").split())


def section_budget(planned: list, index: int, written_before: list[int]) -> int:
    """Wortgrenze für Abschnitt `index`: geplant, abzüglich seines Anteils daran, wie weit die bisherigen Abschnitte
    über ihrem Plan liegen – so gleichen die späteren aus (höchstens bis auf 60 % des Plans; kürzere gleichen nicht
    nach oben aus)."""
    plan = [int(p or 500) for p in planned]
    words = plan[index]
    over = sum(written_before) - sum(plan[:len(written_before)])
    rest = sum(plan[index:])
    if over > 0 and rest:
        words = max(round(0.6 * words), round(words - over * words / rest))
    return words


def unclosed_quote(text: str) -> bool:
    """Steht ein Zitat ohne schliessendes Anführungszeichen im Text (z. B. weil die Ausgabe abbrach)?"""
    for m in re.finditer("„", text):
        rest = text[m.end():]
        close = re.search("[“”]", rest)
        reopen = rest.find("„")
        if not close or (reopen >= 0 and reopen < close.start()):
            return True
    if "„" not in text and text.count("“") != text.count("”"):
        return True
    return text.count("«") != text.count("»") or text.count('"') % 2 == 1


_LIST_OR_TABLE = re.compile(r"^([-*+]\s|\d+[.)]\s|\|)")
_SENTENCE_END = re.compile(r"[.!?:;…)\]»“”\"'*_`]$")


def incomplete_reasons(section: dict, planned_words: int | None = None) -> list[str]:
    """Hinweise, dass ein geschriebener Abschnitt unvollständig ist: vom Anbieter abgebrochen („stopped:…“), Zitat
    ohne Schluss („quote“), endet mitten im Satz („sentence“) oder deutlich kürzer als geplant („short“)."""
    text = (section.get("text") or "").rstrip()
    reasons = [f"stopped:{section['stopped']}"] if section.get("stopped") else []
    if unclosed_quote(text):
        reasons.append("quote")
    last = text.splitlines()[-1].strip() if text else ""
    if not text or (not _LIST_OR_TABLE.match(last) and not _SENTENCE_END.search(last)):
        reasons.append("sentence")
    words = len(text.split())
    if planned_words and words < 0.5 * int(planned_words):
        reasons.append("short")
    # „Kürzer als geplant“ allein ist kein Fehler – nur zusammen mit einem anderen Hinweis melden
    return reasons if any(r != "short" for r in reasons) else []


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        k = x.casefold()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


# Ausgabe je Auswertungsblatt (sichtbarer JSON-Text) – Erfahrungswerte; Denk-Tokens kommen je nach Modell dazu
SHEET_OUTPUT_TOKENS = (800, 1500)
THINKING_FACTOR = {"": (0.0, 2.0), "low": (0.3, 1.0), "medium": (1.0, 2.5), "high": (2.0, 5.0),
                   "xhigh": (3.0, 7.0), "max": (4.0, 10.0)}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[­​]", "", s)
    s = re.sub(r"[‐‑‒–—-]\s*", "", s)
    return re.sub(r"[^\w]+", " ", s).strip()


_CITE_PART = re.compile(r"@?\s*([A-Z0-9]{8})\b[\s,;:]*(?:(?:S\.|p\.|pp\.|Seite)\s*)?(.*)", re.IGNORECASE)

# Quelle ohne gedruckte Seitenzahlen (Bericht, Webseite …) – wird so im Text und in Exporten angegeben
NO_PAGE = "o. S."
_NO_PAGE_RE = re.compile(r"^(?:o\.?\s*S|n\.?\s*p(?:ag)?|ohne\s+Seite(?:nzahl)?)\.?$", re.IGNORECASE)
# Stand der Seitenangaben in Auswertungsblättern und Texten: 2 = gedruckte Seitenzahlen (statt Dateiseiten)
PAGES_VERSION = 2


def parse_citation(group: str) -> list[tuple[str, str]]:
    """'@KEY1, S. 12; @KEY2; @KEY3, o. S.' → [('KEY1', '12'), ('KEY2', ''), ('KEY3', 'o. S.')]"""
    out = []
    for part in group.split(";"):
        m = _CITE_PART.match(part.strip())
        if m:
            page = m.group(2).strip().rstrip(".")
            out.append((m.group(1).upper(), NO_PAGE if _NO_PAGE_RE.match(page) else page))
    return out


_NAME_TAIL = r"(?:\s+(?:et\s+al\.|u\.\s?a\.)|(?:\s*,\s*[^\s,\[\]]+)*,?\s+(?:and|und|&)\s+[^\s,\[\]]+)?"


def named_before(before: str, item: dict) -> bool:
    """Steht die erste Autorin bzw. der erste Autor direkt vor dem Beleg („Shin et al. [@KEY]“, „Shin und Kim [@KEY]“)?
    Dann nennt der Beleg nur Jahr und Seite (in Zotero: suppress-author) – sonst stünde der Name doppelt da."""
    creators = item.get("creators") or []
    first = next((c for role in ("author", "editor", None) for c in creators
                  if role is None or (c.get("creatorType") or "author") == role), None)
    family = strip_bidi((first or {}).get("lastName") or (first or {}).get("name") or "").strip()
    return bool(family) and bool(re.search(r"(?<![\w-])" + re.escape(family) + _NAME_TAIL + r"\s*$", before[-200:]))


def format_citation(parts: list[tuple[str, str]]) -> str:
    """Gegenstück zu parse_citation: [('KEY1', '12'), ('KEY3', 'o. S.')] → '[@KEY1, S. 12; @KEY3, o. S.]'"""
    return "[" + "; ".join(f"@{k}" + ("" if not p else f", {p}" if p == NO_PAGE else f", S. {p}")
                           for k, p in parts) + "]"


def _page_breaks(chunk: dict) -> list[list[int]]:
    try:
        return json.loads(chunk.get("page_breaks") or "[]")
    except ValueError:
        return []


def page_at(chunk: dict, offset: int) -> int | None:
    """PDF-Seite (0-basiert) an einer Zeichenposition im Abschnittstext."""
    page = chunk.get("page_start")
    for off, p in _page_breaks(chunk):
        if off > offset:
            break
        page = p
    return page


def _pages_of(text: str, chunk: dict, shift: int = 0) -> list[tuple[str, int | None]]:
    """Text eines Abschnitts in Stücke je PDF-Seite zerlegen; shift = vorne abgeschnittene Zeichen (Überlappung)."""
    page = page_at(chunk, shift)
    cuts = [(off - shift, p) for off, p in _page_breaks(chunk) if off > shift]
    out, pos = [], 0
    for off, p in cuts:
        if off >= len(text):
            break
        out.append((text[pos:off], page))
        pos, page = off, p
    out.append((text[pos:], page))
    return [(t, p) for t, p in out if t.strip()]


def norm_with_positions(text: str) -> tuple[str, list[int]]:
    """Wie _norm (Kleinschreibung, Bindestriche weg, Satzzeichen als ein Leerzeichen), dazu je Zeichen die
    Position im Originaltext – damit lässt sich ein gefundenes Zitat auf seine Seite zurückführen."""
    out: list[str] = []
    pos: list[int] = []
    space = True
    after_dash = False
    for i, ch in enumerate(text):
        if ch in "­​":
            continue
        for c in unicodedata.normalize("NFKC", ch).lower():
            if c in "‐‑‒–—-":
                after_dash = True
                continue
            if c.isalnum() or c == "_":
                out.append(c)
                pos.append(i)
                space = after_dash = False
            elif not space and not after_dash:
                out.append(" ")
                pos.append(i)
                space = True
    while out and out[-1] == " ":
        out.pop()
        pos.pop()
    return "".join(out), pos


def _strip_overlap(prev: str, text: str) -> str:
    for size in range(min(len(prev), len(text), 800), 20, -1):
        if prev.endswith(text[:size]):
            return text[size:].lstrip()
    return text


class ReviewService:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.store = engine.store
        self.searcher = Searcher(engine)

    # -- Hilfen ---------------------------------------------------------------------
    def _model(self, which: str, job: Job | None) -> tuple[ChatModel, str]:
        cfg = self.engine.settings.llm
        meter = job.meter if job else None
        if which == "helper":
            return helper_model(cfg, meter), cfg.helper_effort
        return main_model(cfg, meter), cfg.effort

    def _language(self, state: dict) -> str:
        return LANG_NAMES.get(state.get("language", "de"), "Deutsch")

    def _filter(self, state: dict) -> SearchFilter:
        return self.engine.make_filter(state.get("filters"))

    def create(self, title: str, question: str, filters: dict | None = None, language: str = "de",
               target_words: int | None = None, project_id: int | None = None) -> int:
        title = (title or "").strip()
        state = {
            "step": "created",
            "filters": filters or {},
            "language": language,
            "target_words": target_words or self.engine.settings.review.target_words,
            # Ohne eigenen Titel schlägt das Hilfsmodell beim Erstellen der Suchstrategie einen vor
            "auto_title": not title,
            "queries": [], "query_stats": [], "searched_at": None,
            "collection_key": None, "outline": None, "sections": [], "check": None,
        }
        return self.store.create_review(title or question, question, state, project_id=project_id)

    def set_title(self, review_id: int, title: str) -> None:
        title = (title or "").strip()
        if not title:
            raise ValueError("Bitte einen Titel angeben.")
        review = self.store.get_review(review_id)
        state = review["state"]
        state["auto_title"] = False
        self.store.update_review_state(review_id, state)
        self.store.update_review_title(review_id, title)

    # ------------------------------------------------------------------------------
    # Schritt 1a: Suchstrategie (Vorschlag, von der Nutzerin bzw. dem Nutzer bearbeitbar)
    # ------------------------------------------------------------------------------
    def generate_strategy(self, job: Job, review_id: int) -> dict:
        review = self.store.get_review(review_id)
        state, question = review["state"], review["question"]
        rcfg = self.engine.settings.review
        job.update(phase="Suchstrategie", message="Formuliere Suchanfragen …")
        helper, effort = self._model("helper", job)
        data = helper.complete_json(
            "Du formulierst Suchanfragen für wissenschaftliche Literaturrecherchen. Antworte nur mit JSON.",
            REVIEW_QUERY_PROMPT.format(question=question, n=rcfg.n_queries,
                                       title_rule=TITLE_RULE if state.get("auto_title") else ""),
            GenParams(max_tokens=4000, effort=effort),
        ) or {}
        queries = [q.strip() for q in data.get("queries", []) if isinstance(q, str) and q.strip()]
        state["queries"] = _dedupe([question] + queries)
        state["query_stats"] = []
        if state["step"] == "created":
            state["step"] = "strategy"
        title = str(data.get("title") or "").strip().strip('"„“')
        if state.get("auto_title") and title:
            self.store.update_review_title(review_id, title[:140])
        self.store.update_review_state(review_id, state)
        job.update(phase="Fertig", message=f"{len(state['queries'])} Suchanfragen vorgeschlagen")
        return {"queries": len(state["queries"])}

    def set_strategy(self, review_id: int, queries: list) -> None:
        if not isinstance(queries, list):
            raise ValueError("Ungültige Suchanfragen")
        cleaned = _dedupe([str(q).strip() for q in queries if str(q).strip()])
        if not cleaned:
            raise ValueError("Mindestens eine Suchanfrage angeben.")
        if len(cleaned) > 80:
            raise ValueError("Höchstens 80 Suchanfragen.")
        review = self.store.get_review(review_id)
        state = review["state"]
        state["queries"] = cleaned
        if state["step"] == "created":
            state["step"] = "strategy"
        self.store.update_review_state(review_id, state)

    def _items(self, keys) -> dict:
        """Einträge der Auswahl; in Zotero gelöschte mit ihren gespeicherten Kurzangaben (removed=True)."""
        keys = list(keys)
        items = self.store.items(keys)
        gone = [k for k in keys if k not in items]
        if gone:
            items.update(self.store.removed_items(gone))
        return items

    def get(self, review_id: int) -> dict:
        review = self.store.get_review(review_id)
        if not review:
            raise KeyError(review_id)
        docs = self.store.review_docs(review_id)
        # Texte, die in Zotero gelöscht wurden: Belege auf eine noch vorhandene Kopie desselben Werks umstellen
        present = self.store.items((d["lib"], d["item_key"]) for d in docs)
        if any((d["lib"], d["item_key"]) not in present for d in docs):
            from zotivity import references

            try:
                if references.repair(self.engine).get("replaced"):
                    review = self.store.get_review(review_id)
                    docs = self.store.review_docs(review_id)
            except Exception as e:  # noqa: BLE001 - die Anzeige darf daran nicht scheitern
                log.warning("Belege auf gelöschte Einträge nicht umgestellt: %s", e)
        items = self._items((d["lib"], d["item_key"]) for d in docs)
        for d in docs:
            it = items.get((d["lib"], d["item_key"]), {})
            d["title"] = it.get("title", "")
            d["citation"] = author_year(it) if it else d["item_key"]
            d["removed"] = bool(it.get("removed"))
            d["has_sheet"] = self.store.get_sheet(d["lib"], d["item_key"]) is not None
            d["zotero_select"] = zotero_select_url(d["lib"], d["item_key"])
        review["docs"] = docs
        # Prüfung aus einer älteren Version (ohne unvollständige oder zu lange Abschnitte, gelöschte Texte): auffrischen
        check = review["state"].get("check")
        if check and any(k not in check for k in ("incomplete_sections", "removed_docs", "long_sections")) \
                and review["state"].get("sections"):
            try:
                review["state"]["check"] = self.check(review_id)
            except Exception as e:  # noqa: BLE001 - die Anzeige darf daran nicht scheitern
                log.warning("Prüfung nicht aufgefrischt: %s", e)
        return review

    # ------------------------------------------------------------------------------
    # Schritt 1: Kandidaten
    # ------------------------------------------------------------------------------
    def find_candidates(self, job: Job, review_id: int) -> dict:
        review = self.store.get_review(review_id)
        state, question = review["state"], review["question"]
        rcfg = self.engine.settings.review
        if not state.get("queries"):
            try:
                self.generate_strategy(job, review_id)
            except LLMError as e:
                job.note(f"Suchanfragen konnten nicht erzeugt werden: {e}")
            review = self.store.get_review(review_id)
            state = review["state"]
        queries = state.get("queries") or [question]
        job.note(f"{len(queries)} Suchanfragen")

        job.update(phase="Suche", message=f"{len(queries)} Suchanfragen – Treffer je Dokument zählen …")
        stats: list[dict] = []
        docs = self.searcher.rank_documents(queries, self._filter(state), self.engine.settings.retrieval,
                                            per_query_k=rcfg.per_query_k, top_docs=rcfg.candidate_docs,
                                            query_stats=stats)
        state["query_stats"] = stats
        state["searched_at"] = time.time()
        job.note(f"{len(docs)} Kandidaten")

        # Vorauswahl anhand Abstract bzw. bester Textstellen
        screen_model, screen_effort = self._model(rcfg.screening_model, job)
        items = self.store.items((d["lib"], d["item_key"]) for d in docs)
        best_rows = self.store.chunk_rows([cid for d in docs for cid in d["best"]])
        key_map = {}
        entries = []
        for d in docs:
            it = items.get((d["lib"], d["item_key"]), {})
            key_map[d["item_key"]] = d
            abstract = (it.get("abstract") or "").strip()
            if len(abstract) < 200:
                excerpts = " … ".join(best_rows[c]["text"][:500] for c in d["best"] if c in best_rows)
                abstract = (abstract + " " if abstract else "") + f"[Auszüge] {excerpts}"
            entries.append(f"[{d['item_key']}] {author_year(it)}: {it.get('title', '')}\n{abstract[:1800]}")

        job.update(phase="Vorauswahl", total=len(entries), done=0)
        batch = 12
        for i in range(0, len(entries), batch):
            job.check()
            chunk = entries[i : i + batch]
            try:
                data = screen_model.complete_json(
                    SCREEN_SYSTEM, SCREEN_PROMPT.format(question=question, docs="\n\n".join(chunk)),
                    GenParams(max_tokens=6000, effort=screen_effort),
                )
                for dec in (data or {}).get("decisions", []):
                    d = key_map.get(str(dec.get("key", "")).strip("[] "))
                    if d is not None:
                        d["decision"] = dec.get("decision", "maybe")
                        d["reason"] = dec.get("reason", "")
            except LLMError as e:
                job.note(f"Vorauswahl-Fehler: {e}")
            job.step(len(chunk), f"{min(i + batch, len(entries))} von {len(entries)} geprüft")

        for d in docs:
            d.setdefault("decision", "maybe")
            d.setdefault("reason", "nicht bewertet")
            d["included"] = d["decision"] == "include"
        self.store.put_review_docs(review_id, docs)
        state["step"] = "candidates"
        self.store.update_review_state(review_id, state)
        n_inc = sum(1 for d in docs if d["included"])
        job.update(phase="Fertig", message=f"{n_inc} Texte vorgeschlagen, {len(docs) - n_inc} weitere zur Prüfung")
        return {"candidates": len(docs), "included": n_inc}

    def export_collection(self, review_id: int) -> dict:
        """Ausgewählte Texte als Zotero-Sammlung anlegen (zum Prüfen und Ergänzen in Zotero)."""
        review = self.store.get_review(review_id)
        state = review["state"]
        docs = [d for d in self.store.review_docs(review_id) if d["included"]]
        zot = self.engine.zotero()
        by_lib: dict[str, list[str]] = {}
        for d in docs:
            by_lib.setdefault(d["lib"], []).append(d["item_key"])
        lib = next(iter(by_lib), "users/0")
        if not state.get("collection_key"):
            name = f"Zotivity – {review['title'][:80]}"
            state["collection_key"] = zot.create_collection(lib, name)
            state["collection_lib"] = lib
        added = zot.add_to_collection(lib, state["collection_key"], by_lib.get(lib, []))
        self.store.update_review_state(review_id, state)
        return {"collection_key": state["collection_key"], "added": added}

    def import_collection(self, review_id: int) -> dict:
        """Auswahl aus der (in Zotero ergänzten) Sammlung übernehmen."""
        review = self.store.get_review(review_id)
        state = review["state"]
        if not state.get("collection_key"):
            raise ValueError("Für diesen Forschungsstand wurde noch keine Zotero-Sammlung angelegt.")
        lib = state.get("collection_lib", "users/0")
        zot = self.engine.zotero()
        keys = set(zot.item_keys(lib, collection=state["collection_key"]))
        top = {it["key"] for it in zot.iter_items(lib, keys=list(keys)) if it["data"].get("itemType") not in
               ("attachment", "note", "annotation")} if keys else set()
        docs = self.store.review_docs(review_id)
        known = {d["item_key"] for d in docs}
        for d in docs:
            d["included"] = d["item_key"] in top
        for k in top - known:
            docs.append({"lib": lib, "item_key": k, "score": 0, "hits": 0, "decision": "manual",
                         "reason": "in Zotero ergänzt", "included": True})
        self.store.put_review_docs(review_id, docs)
        return {"included": len(top), "added": len(top - known)}

    def confirm(self, review_id: int) -> None:
        review = self.store.get_review(review_id)
        state = review["state"]
        state["step"] = "confirmed"
        self.store.update_review_state(review_id, state)

    # ------------------------------------------------------------------------------
    # Schritt 2: Auswertungsblätter
    # ------------------------------------------------------------------------------
    def document_text(self, lib: str, item_key: str, focus_queries: list[str] | None, limit_tokens: int,
                      relevant_chunks: int) -> tuple[str, str]:
        """Text mit Seitenmarkierungen [S. x]. Rückgabe (text, basis)."""
        rows = [r for r in self.store.document_chunks(lib, item_key) if r["kind"] in ("text", "abstract")]
        if not rows:
            return "", "kein Text"
        abstract = next((r["text"] for r in rows if r["kind"] == "abstract"), "")
        body = [r for r in rows if r["kind"] == "text"]
        total = sum(estimate_tokens(r["text"]) for r in body)
        if total <= limit_tokens:
            selected, basis = body, "Volltext"
        else:
            keep: set[int] = set(r["id"] for r in body[:4]) | set(r["id"] for r in body[-3:])
            if focus_queries:
                try:
                    emb = self.engine.embedder()
                    _, vi = self.engine.vector_index()
                    ids = np.asarray(sorted(r["id"] for r in body), dtype=np.int64)
                    q = emb.embed_queries(focus_queries[:6]).mean(axis=0)
                    for cid, _ in vi.search(q, relevant_chunks, ids):
                        keep.add(cid)
                except Exception as e:  # noqa: BLE001
                    log.warning("Fokussuche im Dokument nicht möglich: %s", e)
            if len(keep) < relevant_chunks:
                step = max(1, len(body) // relevant_chunks)
                keep.update(r["id"] for r in body[::step])
            selected = [r for r in body if r["id"] in keep]
            basis = f"Auszüge ({len(selected)} von {len(body)} Abschnitten)"
        parts: list[str] = []
        if abstract:
            parts.append(f"[Abstract]\n{abstract}")
        prev, last_marker = None, None
        labels_of: dict[str, list[str] | None] = {}
        for r in selected:
            contiguous = prev is not None and r["att_key"] == prev["att_key"] and r["ord"] == prev["ord"] + 1
            text = _strip_overlap(prev["text"], r["text"]) if contiguous else r["text"]
            if prev is not None and not contiguous:
                parts.append("[…]")
            if r["att_key"] not in labels_of:
                labels_of[r["att_key"]] = self.store.page_labels(lib, r["att_key"])
            labels = labels_of[r["att_key"]]
            # Seitenmarken auch mitten im Abschnitt, dort wo eine neue Seite beginnt (gedruckte Seite oder o. S.)
            shift = len(r["text"]) - len(text)
            for piece, page_index in _pages_of(text, r, shift):
                marker = self._marker(labels, page_index, r["page_label"])
                if marker and marker != last_marker:
                    parts.append(marker)
                    last_marker = marker
                parts.append(piece)
            prev = r
        return "\n\n".join(p for p in parts if p.strip()), basis

    @staticmethod
    def _marker(labels: list[str] | None, page_index: int | None, chunk_label: str) -> str:
        """[S. 114] bzw. [o. S.] für eine PDF-Seite; ohne erkannte Seitenzahlen (alter Index) die Abschnittsangabe."""
        if labels is None:
            page = (chunk_label or "").split("–")[0]
            return f"[S. {page}]" if page else ""
        if page_index is None or page_index >= len(labels):
            return ""
        return f"[S. {labels[page_index]}]" if labels[page_index] else f"[{NO_PAGE}]"

    def sheet_language(self, language: str | None = None) -> str:
        """Sprache der Auswertungsblätter: die des Forschungsstands, sonst Einstellung bzw. Oberfläche."""
        s = self.engine.settings
        lang = language or (s.output_language if s.output_language != "auto" else s.language)
        return f"Schreibe auf {LANG_NAMES.get(lang, lang)};"

    def make_sheet(self, model: ChatModel, effort: str, lib: str, item_key: str, focus: list[str] | None,
                   language: str | None = None) -> dict:
        rcfg = self.engine.settings.review
        item = self.store.item(lib, item_key) or {}
        text, basis = self.document_text(lib, item_key, focus, rcfg.fulltext_token_limit, rcfg.relevant_chunks_if_long)
        if not text:
            raise ValueError("Kein indexierter Text vorhanden")
        prompt = (
            f"Text: {author_year(item)}: {item.get('title', '')} ({item.get('publication', '')})\n"
            f"Grundlage: {basis}\n\n{text}\n\n---\n\nErstelle das Auswertungsblatt in diesem JSON-Format:\n{SHEET_SCHEMA}"
        )
        data = model.complete_json(SHEET_SYSTEM.format(language_rule=self.sheet_language(language)), prompt,
                                   GenParams(max_tokens=8000, effort=effort))
        if not isinstance(data, dict):
            raise ValueError("Ungültiges Auswertungsblatt")
        data["_basis"] = basis
        data["_version"] = SHEET_VERSION
        # Seiten der Kernzitate nicht dem Modell überlassen: im Text nachschlagen (gedruckte Seite oder o. S.)
        return self.verify_sheet_pages(lib, item_key, data)

    def sheet_note_html(self, lib: str, item_key: str, sheet: dict, model: str) -> str:
        item = self.store.item(lib, item_key) or {}
        e = html.escape
        rows = [f"<h1>Auswertungsblatt: {e(item.get('title', ''))}</h1>",
                f"<p><em>Erstellt von Zotivity ({e(model)}), Grundlage: {e(sheet.get('_basis', ''))}. "
                f"Automatisch erzeugt – bitte prüfen.</em></p>"]
        labels = [("kurzbeschreibung", "Kurzbeschreibung"), ("textsorte", "Textsorte"),
                  ("fragestellung", "Fragestellung"), ("theorie", "Theorie"), ("methode", "Methode"),
                  ("stichprobe", "Stichprobe"), ("land_kontext", "Land/Kontext"), ("zeitraum", "Zeitraum")]
        for key, label in labels:
            if sheet.get(key):
                rows.append(f"<p><strong>{label}:</strong> {e(str(sheet[key]))}</p>")
        if sheet.get("zentrale_befunde"):
            rows.append("<h2>Zentrale Befunde</h2><ul>" +
                        "".join(f"<li>{e(str(b))}</li>" for b in sheet["zentrale_befunde"]) + "</ul>")
        if sheet.get("grenzen"):
            rows.append(f"<p><strong>Grenzen:</strong> {e(str(sheet['grenzen']))}</p>")
        quotes = sheet.get("kernzitate") or []
        if quotes:
            rows.append("<h2>Kernzitate</h2>")
            pdf = self._pdf_attachment(lib, item_key)
            for q in quotes:
                if not isinstance(q, dict):
                    continue
                page = str(q.get("seite", "")).strip()
                shown = page if page == NO_PAGE else f"S. {page}"
                link = ""
                url = self._quote_url(lib, item_key, pdf, q)
                if url:
                    link = f' (<a href="{e(url)}">{e(shown)}</a>)'
                elif page:
                    link = f" ({e(shown)})"
                rows.append(f"<blockquote><p>„{e(str(q.get('zitat', '')))}“{link}</p></blockquote>")
        if sheet.get("stichworte"):
            rows.append(f"<p><strong>Stichworte:</strong> {e(', '.join(map(str, sheet['stichworte'])))}</p>")
        return "\n".join(rows)

    def _quote_url(self, lib: str, item_key: str, pdf: dict | None, q: dict) -> str | None:
        """Link auf die Seite eines Kernzitats in der PDF: die gefundene Dateiseite, sonst aus der Seitenangabe."""
        page = str(q.get("seite", "")).strip()
        if not pdf or not page:
            return None
        pdf_page = q.get("pdf_seite")
        idx = int(pdf_page) - 1 if str(pdf_page or "").isdigit() else self._page_index(lib, item_key, page)
        return zotero_open_pdf_url(lib, pdf["key"], idx)

    def sheet_view(self, lib: str, item_key: str) -> dict | None:
        """Auswertungsblatt zur Anzeige: Felder ohne interne Angaben, Kernzitate mit Link auf die PDF-Seite,
        Modell, Grundlage und – falls gespeichert – die Notiz in Zotero."""
        row = self.ensure_sheet_pages(lib, item_key)
        if not row:
            return None
        sheet = row["sheet"]
        pdf = self._pdf_attachment(lib, item_key)
        quotes = [{"zitat": str(q.get("zitat", "")), "seite": str(q.get("seite", "")).strip(),
                   "url": self._quote_url(lib, item_key, pdf, q)}
                  for q in sheet.get("kernzitate") or [] if isinstance(q, dict)]
        return {"lib": lib, "item_key": item_key, "quotes": quotes,
                "sheet": {k: v for k, v in sheet.items() if not k.startswith("_") and k != "kernzitate"},
                "basis": sheet.get("_basis", ""), "model": row.get("model") or "", "created_at": row.get("created_at"),
                "note_select": zotero_select_url(lib, row["note_key"]) if row.get("note_key") else None}

    def _page_index(self, lib: str, item_key: str, label: str) -> int | None:
        """Seitenangabe eines Belegs („12“, „12–14“, „1, 9“, „12f.“, „xii“) → Seite in der PDF (0-basiert).
        Massgebend ist die erste genannte Seite. Seitenzahlen des Drucks (z. B. 245 in einer Zeitschrift) werden
        über die Seitenangaben der Abschnitte auf die PDF-Seite umgerechnet."""
        if not label or label == NO_PAGE:
            return None
        first = re.split(r"[–—\-,;/\s]+", (label or "").strip())[0].strip().rstrip(".")
        first = re.sub(r"(?<=\d)f{1,2}$", "", first)
        if not first:
            return None
        pdf = self._pdf_attachment(lib, item_key)
        labels = self.store.page_labels(lib, pdf["key"]) if pdf else None
        if labels:  # gedruckte Seitenzahl je PDF-Seite bekannt
            for i, lab in enumerate(labels):
                if lab and lab.casefold() == first.casefold():
                    return i
            numbered = [(int(lab), i) for i, lab in enumerate(labels) if lab.isdigit()]
            if first.isdigit() and numbered:
                printed, index = min(numbered, key=lambda x: abs(x[0] - int(first)))
                return min(len(labels) - 1, max(0, index + int(first) - printed))
            return None
        chunks = [r for r in self.store.document_chunks(lib, item_key) if r["page_start"] is not None]
        numeric: list[tuple[int, int]] = []  # (gedruckte Seite, PDF-Seite)
        for r in chunks:
            parts = [x.strip() for x in re.split(r"[–—\-]", r["page_label"] or "") if x.strip()]
            if parts and parts[0].casefold() == first.casefold():
                return r["page_start"]
            if len(parts) > 1 and parts[-1].casefold() == first.casefold() and r["page_end"] is not None:
                return r["page_end"]
            if parts and parts[0].isdigit():
                numeric.append((int(parts[0]), r["page_start"]))
        if not first.isdigit():
            return None
        n = int(first)
        if numeric:
            printed, index = min(numeric, key=lambda x: abs(x[0] - n))
            return max(0, index + n - printed)
        return n - 1

    def _pdf_attachment(self, lib: str, item_key: str) -> dict | None:
        atts = self.store.attachments_for_item(lib, item_key)
        # Nur Anhänge, die Zotero selbst an einer Seite öffnet – Word & Co. verlinken auf den Eintrag
        return next((a for a in atts if a["content_type"] == "application/pdf" and a["status"] == "indexed"),
                    next((a for a in atts if a["content_type"] == "application/pdf"),
                         next((a for a in atts if opens_in_reader(a["content_type"])), None)))

    def _has_page_labels(self, lib: str, item_key: str) -> bool:
        """Ist der Text mit Erkennung der gedruckten Seitenzahlen indexiert? Nein, solange ein Anhang noch auf das
        (erneute) Lesen wartet oder aus der Zeit davor stammt."""
        atts = self.store.attachments_for_item(lib, item_key)
        if any(a["status"] == "pending" for a in atts):
            return False
        return all(self.store.page_labels(lib, a["key"]) is not None for a in atts if a["status"] == "indexed")

    # -- Gedruckte Seitenzahlen in Auswertungsblättern und Texten ---------------------------------
    def locate_quotes(self, lib: str, item_key: str, quotes: list[str]) -> list[tuple[str, int] | None]:
        """Wo stehen wörtliche Zitate im Text? Je Zitat (Anhang, PDF-Seite 0-basiert) oder None. Verglichen wird
        ohne Gross-/Kleinschreibung, Bindestriche und Satzzeichen; bei längeren Zitaten genügt Anfang, Ende oder
        Mitte (das Sprachmodell kürzt oder glättet gelegentlich)."""
        chunks = [c for c in self.store.document_chunks(lib, item_key)
                  if c["kind"] in ("text", "references") and c["page_start"] is not None]
        normed = [(c, *norm_with_positions(c["text"])) for c in chunks]
        out: list[tuple[str, int] | None] = []
        for quote in quotes:
            q, _ = norm_with_positions(quote or "")
            if len(q) < 12:
                out.append(None)
                continue
            probes = [q]
            if len(q) > 90:
                mid = len(q) // 2
                probes += [q[:60], q[-60:], q[mid - 30:mid + 30]]
            hit = None
            for probe in probes:
                for c, text, pos in normed:
                    i = text.find(probe)
                    if i >= 0:
                        hit = (c["att_key"], page_at(c, pos[i]))
                        break
                if hit:
                    break
            out.append(hit)
        return out

    @staticmethod
    def _convert_page(old: str, labels: list[str]) -> str:
        """Seitenangabe aus der Zeit vor der Seitenzahl-Erkennung (Dateiseite) in die gedruckte Seite umrechnen.
        Schon gültige gedruckte Seiten bleiben; ohne Seitenzahl im Druck wird daraus „o. S.“."""
        if not old or old == NO_PAGE or not labels:
            return old
        valid = {lab for lab in labels if lab}
        missing = False

        def conv(m: re.Match) -> str:
            nonlocal missing
            v = m.group(0)
            if v in valid:
                return v
            idx = int(v) - 1
            if 0 <= idx < len(labels):
                if labels[idx]:
                    return labels[idx]
                missing = True
            return v

        new = re.sub(r"\d+", conv, old)
        return NO_PAGE if missing else new

    def verify_sheet_pages(self, lib: str, item_key: str, sheet: dict) -> dict:
        """Seiten der Kernzitate selbst bestimmen: Zitat im Text suchen → gedruckte Seite (oder „o. S.“) und PDF-Seite
        für den Link. Nicht gefundene Zitate: alte Dateiseite umrechnen. Merkt sich die Zuordnung alt → neu für
        bereits geschriebene Forschungsstände."""
        if not self._has_page_labels(lib, item_key):
            return sheet  # noch ohne Seitenzahl-Erkennung indexiert – später
        quotes = sheet.get("kernzitate")
        changes: dict[str, str] = dict(sheet.get("_seiten_alt") or {})
        if isinstance(quotes, list) and quotes:
            hits = self.locate_quotes(lib, item_key, [str(q.get("zitat", "")) if isinstance(q, dict) else ""
                                                      for q in quotes])
            pdf = self._pdf_attachment(lib, item_key)
            pdf_labels = self.store.page_labels(lib, pdf["key"]) if pdf else None
            label_cache: dict[str, list[str] | None] = {}
            for q, hit in zip(quotes, hits):
                if not isinstance(q, dict):
                    continue
                old = str(q.get("seite", "")).strip()
                if hit and hit[1] is not None:
                    att, page = hit
                    if att not in label_cache:
                        label_cache[att] = self.store.page_labels(lib, att)
                    labels = label_cache[att]
                    if labels is None:
                        continue
                    new = labels[page] if page < len(labels) and labels[page] else NO_PAGE
                    q["pdf_seite"] = page + 1
                elif sheet.get("_seiten") != PAGES_VERSION and pdf_labels is not None:
                    new = self._convert_page(old, pdf_labels)
                else:
                    continue
                if sheet.get("_seiten") != PAGES_VERSION and old and old != new:
                    changes[old] = new
                q["seite"] = new
        if changes:
            sheet["_seiten_alt"] = changes
        sheet["_seiten"] = PAGES_VERSION
        return sheet

    def ensure_sheet_pages(self, lib: str, item_key: str) -> dict | None:
        """Auswertungsblatt aus der Zeit vor der Seitenzahl-Erkennung einmal nachführen (ohne Sprachmodell)."""
        row = self.store.get_sheet(lib, item_key)
        if not row or row["sheet"].get("_seiten") == PAGES_VERSION or not self._has_page_labels(lib, item_key):
            return row
        sheet = self.verify_sheet_pages(lib, item_key, row["sheet"])
        self.store.put_sheet(lib, item_key, sheet, row.get("model") or "", row.get("note_key"))
        return {**row, "sheet": sheet}

    def ensure_review_pages(self, review_id: int) -> None:
        """Seitenangaben eines bereits geschriebenen Forschungsstands auf gedruckte Seiten umstellen – je Text,
        sobald er neu indexiert ist: über die Zuordnung der Kernzitate, sonst durch Umrechnen der Dateiseite."""
        review = self.store.get_review(review_id)
        if not review:
            return
        state = review["state"]
        if not state.get("sections"):
            return
        done = set(state.get("_seiten_ok") or [])
        docs = {d["item_key"]: d for d in self.store.review_docs(review_id)}
        text = "\n\n".join(s["text"] for s in state["sections"])
        cited = {k for m in self._CITE.finditer(text) for k, _ in parse_citation(m.group(1)) if k in docs} - done
        ready: dict[str, tuple[dict, list[str]]] = {}
        for key in cited:
            lib = docs[key]["lib"]
            if not self._has_page_labels(lib, key):
                continue
            row = self.ensure_sheet_pages(lib, key)
            pdf = self._pdf_attachment(lib, key)
            labels = (self.store.page_labels(lib, pdf["key"]) if pdf else None) or []
            ready[key] = ((row or {}).get("sheet") or {}, labels)
        if not ready:
            return

        def fix(m: re.Match) -> str:
            parts = parse_citation(m.group(1))
            if not parts or not any(k in ready for k, _ in parts):
                return m.group(0)
            new = []
            for k, p in parts:
                if k in ready and p:
                    sheet, labels = ready[k]
                    p = (sheet.get("_seiten_alt") or {}).get(p) or self._convert_page(p, labels)
                new.append((k, p))
            return format_citation(new)

        for s in state["sections"]:
            s["text"] = self._CITE.sub(fix, s["text"])
        state["_seiten_ok"] = sorted(done | set(ready))
        self.store.update_review_state(review_id, state)

    # -- Seite für Belege ohne Seitenangabe ------------------------------------------------------
    @classmethod
    def _cite_context(cls, text: str, pos: int) -> str:
        """Der belegte Satz vor einem Beleg (bei sehr kurzen Sätzen samt dem vorigen); steht der Beleg am
        Absatzanfang, der Satz danach."""
        cite = cls._CITE
        before = cite.sub(" ", text[max(0, pos - 800):pos].split("\n\n")[-1])
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", before.strip()) if s.strip()]
        ctx = sentences[-1] if sentences else ""
        if len(ctx) < 80 and len(sentences) > 1:
            ctx = f"{sentences[-2]} {ctx}"
        if len(ctx.strip()) < 20:
            after = cite.sub(" ", text[pos:pos + 600].split("\n\n")[0])
            ctx = f"{ctx} {re.split(r'(?<=[.!?])\s+', after.strip())[0]}"
        return re.sub(r"\s+", " ", ctx).strip(" #*-")[-600:]

    @staticmethod
    def _page_ref(key: str, context: str) -> str:
        import hashlib

        return f"{key}|{hashlib.sha1(context.encode('utf-8')).hexdigest()[:12]}"

    def locate_pages(self, review_id: int, text: str | None = None) -> dict[str, int | None]:
        """PDF-Seite (0-basiert) je Beleg ohne Seitenangabe: der Abschnitt des zitierten Texts, der dem belegten
        Satz am ähnlichsten ist. Gemerkt je Forschungsstand und Belegstelle (Schlüssel + Satz) – ändert sich der
        Text, wird nur für neue Stellen gesucht."""
        if text is None:
            review = self.store.get_review(review_id)
            text = "\n\n".join(s["text"] for s in (review["state"] if review else {}).get("sections", []))
        docs = {d["item_key"]: d for d in self.store.review_docs(review_id)}
        known = self.store.review_pages(review_id)
        todo: dict[str, tuple[str, str, str]] = {}
        for m in self._CITE.finditer(text):
            ctx = None
            for key, page in parse_citation(m.group(1)):
                if (page and page != NO_PAGE) or key not in docs:
                    continue
                ctx = ctx if ctx is not None else self._cite_context(text, m.start())
                ref = self._page_ref(key, ctx)
                if ref not in known and ref not in todo:
                    todo[ref] = (docs[key]["lib"], key, ctx)
        if todo:
            # Steht vor dem Beleg ein wörtliches Zitat, ist dessen Fundstelle genau; sonst die ähnlichste Stelle
            found: list[int | None] = [None] * len(todo)
            rest = []
            for i, (lib, key, ctx) in enumerate(todo.values()):
                quote = max(re.findall(r"[„“\"«»]([^„“\"«»]{20,600})[“”\"«»]", ctx), key=len, default="")
                hit = self.locate_quotes(lib, key, [quote])[0] if quote else None
                if hit and hit[1] is not None:
                    found[i] = hit[1]
                else:
                    rest.append(i)
            items = list(todo.values())
            for i, page in zip(rest, self._best_pages([items[i] for i in rest]) if rest else []):
                found[i] = page
            new = dict(zip(todo, found))
            self.store.put_review_pages(review_id, new)
            known.update(new)
        return known

    _WORD = re.compile(r"\w{4,}", re.UNICODE)

    def _best_pages(self, items: list[tuple[str, str, str]]) -> list[int | None]:
        """Für (lib, key, Satz): Seite des ähnlichsten Abschnitts. Embeddings (mehrsprachig – der Forschungsstand ist
        oft deutsch, die Quelle englisch), ergänzt um gemeinsame Wörter; ohne Embeddings nur die Wörter."""
        from zotivity.index.vectors import normalize

        chunks: dict[tuple[str, str], list[dict]] = {}
        for lib, key, _ in items:
            if (lib, key) not in chunks:
                chunks[(lib, key)] = [c for c in self.store.document_chunks(lib, key)
                                      if c["page_start"] is not None and c["kind"] not in ("references", "abstract")]
        vectors: dict[int, np.ndarray] = {}
        queries = None
        try:
            _, vi = self.engine.vector_index()
            vectors = vi.vectors_for([c["id"] for cs in chunks.values() for c in cs])
            if vectors:
                texts = [ctx for _, _, ctx in items]
                emb = self.engine.embedder()
                queries = normalize(np.concatenate([emb.embed_queries(texts[i:i + 64]) for i in range(0, len(texts), 64)]))
        except Exception as e:  # noqa: BLE001 – ohne Embeddings bleibt der Wortvergleich
            log.info("Seitensuche für Belege ohne Embeddings: %s", e)
            queries = None
        out: list[int | None] = []
        for i, (lib, key, ctx) in enumerate(items):
            cs = chunks[(lib, key)]
            if not cs:
                out.append(None)
                continue
            words = [set(self._WORD.findall(_norm(c["text"]))) for c in cs]
            df: dict[str, int] = {}
            for ws in words:
                for w in ws:
                    df[w] = df.get(w, 0) + 1
            q = set(self._WORD.findall(_norm(ctx)))
            lexical = np.array([sum(np.log(1 + len(cs) / df[w]) for w in q & ws) for ws in words], dtype=np.float32)
            if lexical.max() > 0:
                lexical /= lexical.max()
            score = 0.25 * lexical
            if queries is not None:
                dense = np.array([float(vectors[c["id"]] @ queries[i]) if c["id"] in vectors else -1.0 for c in cs],
                                 dtype=np.float32)
                score = dense + score
            out.append(int(cs[int(np.argmax(score))]["page_start"]))
        return out

    def build_sheets(self, job: Job, docs: list[tuple[str, str]], focus: list[str] | None = None,
                     model_choice: str | None = None, overwrite: bool = False, language: str | None = None) -> dict:
        rcfg = self.engine.settings.review
        model, effort = self._model(model_choice or rcfg.sheet_model, job)
        todo = [(lib, k) for lib, k in docs if overwrite or not self.store.get_sheet(lib, k)]
        job.update(phase="Auswertungsblätter", total=len(docs), done=len(docs) - len(todo),
                   message=f"{len(todo)} Blätter zu erstellen ({len(docs) - len(todo)} vorhanden)")
        write_notes = rcfg.write_notes_to_zotero
        zot = self.engine.zotero() if write_notes else None
        result = {"created": 0, "errors": 0, "notes": 0}

        def work(lib, key):
            job.check()
            return lib, key, self.make_sheet(model, effort, lib, key, focus, language)

        with ThreadPoolExecutor(max_workers=rcfg.parallel_requests) as ex:
            futures = [ex.submit(work, lib, k) for lib, k in todo]
            for fut in as_completed(futures):
                try:
                    lib, key, sheet = fut.result()
                except Exception as e:  # noqa: BLE001
                    if job.cancelled:
                        break
                    result["errors"] += 1
                    result["error"] = str(e)
                    job.note(f"Auswertung fehlgeschlagen: {e}")
                    job.step()
                    continue
                existing = self.store.get_sheet(lib, key)
                note_key = existing.get("note_key") if existing else None
                self.store.put_sheet(lib, key, sheet, model.label, note_key)
                result["created"] += 1
                if zot is not None:
                    try:
                        note_html = self.sheet_note_html(lib, key, sheet, model.label)
                        if note_key:
                            zot.update_note(lib, note_key, note_html)
                        else:
                            note_key = zot.create_note(lib, key, note_html, tags=[rcfg.note_tag])
                            self.store.set_sheet_note(lib, key, note_key)
                        result["notes"] += 1
                    except ZoteroAuthRequired:
                        job.note("Notizen nicht gespeichert: Schreibzugriff auf Zotero nicht freigegeben.")
                        zot = None
                    except ZoteroError as e:
                        job.note(f"Notiz nicht gespeichert: {e}")
                item = self.store.item(lib, key) or {}
                job.step(1, f"{author_year(item)}: {item.get('title', '')[:80]}")
            if job.cancelled:
                for f in futures:
                    f.cancel()
        job.check()
        return result

    def estimate_extraction(self, review_id: int) -> dict:
        """Umfang von Schritt 2: Eingabe-Tokens (gezählt), Ausgabe- und Denk-Tokens (Spanne), Kosten (falls Preise
        für das Modell hinterlegt sind)."""
        settings = self.engine.settings
        rcfg, llm = settings.review, settings.llm
        docs = [d for d in self.store.review_docs(review_id) if d["included"]]
        total, missing = 0, 0
        for d in docs:
            if self.store.get_sheet(d["lib"], d["item_key"]):
                continue
            missing += 1
            toks = sum(estimate_tokens(r["text"]) for r in self.store.document_chunks(d["lib"], d["item_key"])
                       if r["kind"] == "text")
            total += min(toks, rcfg.fulltext_token_limit) + 1500
        main = rcfg.sheet_model == "main"
        model = llm.model if main else llm.helper_model
        effort = llm.effort if main else llm.helper_effort
        out_lo, out_hi = (missing * SHEET_OUTPUT_TOKENS[0], missing * SHEET_OUTPUT_TOKENS[1])
        f_lo, f_hi = THINKING_FACTOR.get(effort, (0.0, 2.0))
        think_lo, think_hi = int(out_lo * f_lo), int(out_hi * f_hi)
        result = {"documents": len(docs), "missing_sheets": missing, "input_tokens": total,
                  "output_tokens": [out_lo, out_hi], "thinking_tokens": [think_lo, think_hi],
                  "model": model, "effort": effort, "currency": llm.price_currency, "cost": None}
        price = llm.prices.get(model)
        if price and len(price) == 2:
            p_in, p_out = price
            result["cost"] = [round(total / 1e6 * p_in + (out_lo + think_lo) / 1e6 * p_out, 2),
                              round(total / 1e6 * p_in + (out_hi + think_hi) / 1e6 * p_out, 2)]
        return result

    def extract(self, job: Job, review_id: int) -> dict:
        review = self.store.get_review(review_id)
        state = review["state"]
        docs = [(d["lib"], d["item_key"]) for d in self.store.review_docs(review_id) if d["included"]]
        if not docs:
            raise ValueError("Keine Texte ausgewählt.")
        res = self.build_sheets(job, docs, focus=state.get("queries") or [review["question"]],
                                language=state.get("language"))
        state["step"] = "extracted"
        self.store.update_review_state(review_id, state)
        job.update(phase="Fertig", message=f"{res['created']} Blätter erstellt, {res['notes']} Notizen in Zotero")
        return res

    def rebuild_sheet(self, job: Job, review_id: int, lib: str, item_key: str) -> dict:
        """Ein einzelnes Auswertungsblatt neu erstellen (etwa ein schwaches); der übrige Forschungsstand bleibt."""
        review = self.store.get_review(review_id)
        if not review:
            raise KeyError(review_id)
        if not self.store.get_sheet(lib, item_key):
            raise ValueError("Für diesen Text gibt es noch kein Auswertungsblatt.")
        state = review["state"]
        res = self.build_sheets(job, [(lib, item_key)], focus=state.get("queries") or [review["question"]],
                                overwrite=True, language=state.get("language"))
        if not res["created"]:
            raise ValueError(f"Auswertungsblatt nicht neu erstellt: {res.get('error') or '?'}")
        job.update(phase="Fertig", message="Auswertungsblatt neu erstellt")
        return res

    # ------------------------------------------------------------------------------
    # Schritt 3: Synthese
    # ------------------------------------------------------------------------------
    def _sheets_block(self, review_id: int) -> tuple[str, dict[str, dict]]:
        docs = [d for d in self.store.review_docs(review_id) if d["included"]]
        items = self.store.items((d["lib"], d["item_key"]) for d in docs)
        blocks, meta = [], {}
        for d in docs:
            sheet = self.ensure_sheet_pages(d["lib"], d["item_key"])
            if not sheet:
                continue
            it = items.get((d["lib"], d["item_key"]), {})
            s = {k: v for k, v in sheet["sheet"].items() if not k.startswith("_")}
            if isinstance(s.get("kernzitate"), list):  # PDF-Seite nur für Links, nicht für das Modell
                s["kernzitate"] = [{k: v for k, v in q.items() if k != "pdf_seite"} if isinstance(q, dict) else q
                                   for q in s["kernzitate"]]
            blocks.append(f"[{d['item_key']}] {author_year(it)}: {it.get('title', '')}\n"
                          f"{json.dumps(s, ensure_ascii=False)}")
            meta[d["item_key"]] = {"lib": d["lib"], "item": it}
        return "\n\n".join(blocks), meta

    def outline(self, job: Job, review_id: int) -> dict:
        review = self.store.get_review(review_id)
        state = review["state"]
        sheets, meta = self._sheets_block(review_id)
        if not meta:
            raise ValueError("Keine Auswertungsblätter vorhanden – zuerst Schritt 2 ausführen.")
        model, effort = self._model("main", job)
        job.update(phase="Gliederung", message=f"Gliederung aus {len(meta)} Auswertungsblättern …")
        data = model.complete_json(
            OUTLINE_SYSTEM,
            OUTLINE_PROMPT.format(question=review["question"], words=state["target_words"],
                                  language=self._language(state), n=len(meta), sheets=sheets),
            GenParams(max_tokens=8000, effort=effort),
        )
        if not isinstance(data, dict) or not data.get("sections"):
            raise ValueError("Die Gliederung konnte nicht erstellt werden.")
        state["outline"] = data
        state["sections"] = []
        state["step"] = "outlined"
        self.store.update_review_state(review_id, state)
        job.update(phase="Fertig", message=f"{len(data['sections'])} Abschnitte geplant")
        return data

    def set_outline(self, review_id: int, outline: dict) -> None:
        review = self.store.get_review(review_id)
        state = review["state"]
        if not isinstance(outline, dict) or not isinstance(outline.get("sections"), list):
            raise ValueError("Ungültige Gliederung")
        state["outline"] = outline
        state["sections"] = []
        self.store.update_review_state(review_id, state)

    def _write_context(self, review_id: int, job: Job) -> tuple[dict, dict, dict, ChatModel, str, str, str]:
        review = self.store.get_review(review_id)
        state = review["state"]
        outline = state.get("outline")
        if not outline:
            raise ValueError("Zuerst die Gliederung erstellen.")
        sheets, meta = self._sheets_block(review_id)
        model, effort = self._model("main", job)
        outline_text = "\n".join(
            f"{i + 1}. {s.get('heading')} – {s.get('focus', '')} (~{s.get('words', '?')} Wörter)"
            for i, s in enumerate(outline["sections"])
        )
        return review, state, meta, model, effort, WRITE_SYSTEM.format(sheets=sheets), outline_text

    def _write_section(self, review: dict, state: dict, model: ChatModel, effort: str, system: str, outline_text: str,
                       sec: dict, before: list[dict]) -> dict:
        """Einen Abschnitt schreiben. Bricht die Ausgabe ab (Ausgabelimit oder – bei Gemini – Sperre wegen wörtlicher
        Wiedergabe), wird er einmal neu geschrieben: mit mehr Platz bzw. der Vorgabe, kürzer wörtlich zu zitieren.
        Bleibt er abgeschnitten, ist das am Abschnitt vermerkt („stopped“) und die Prüfung meldet ihn."""
        llm_cfg = self.engine.settings.llm
        planned = [s.get("words") for s in state["outline"]["sections"]]
        index = len(before)
        written = [count_words(s["text"]) for s in before]
        words = section_budget(planned, index, written) if index < len(planned) else int(sec.get("words") or 500)
        budget = ""
        if written:
            budget = (f" Die bisherigen Abschnitte haben {sum(written)} Wörter; für den ganzen Text sind etwa "
                      f"{sum(int(p or 500) for p in planned)} vorgesehen.")
        prompt = WRITE_PROMPT.format(
            question=review["question"], language=self._language(state), outline=outline_text,
            previous="\n\n".join(s["text"] for s in before) or "(noch keine)", heading=sec.get("heading", ""),
            focus=sec.get("focus", ""), words=words, low=round(0.8 * words), budget=budget,
            keys=", ".join(sec.get("keys", [])) or "alle passenden",
        )
        params = GenParams(max_tokens=max(4000, min(llm_cfg.max_output_tokens, words * 4 + 4000)),
                           temperature=llm_cfg.temperature, effort=effort)
        c = model.complete(system, [ChatMessage("user", prompt)], params)
        text, stopped = c.text.strip(), truncation(c.stop_reason)
        if stopped:
            log.warning("Abschnitt „%s“ abgebrochen (%s) – zweiter Versuch", sec.get("heading", ""), c.stop_reason)
            cap = max(llm_cfg.max_output_tokens, params.max_tokens * 2)
            params2, prompt2 = retry_after_truncation(stopped, params, prompt, cap)
            if stopped == "length":  # ein einzelner Abschnitt: gleich mit dem eingestellten Maximum
                params2 = replace(params2, max_tokens=cap)
            c2 = model.complete(system, [ChatMessage("user", prompt2)], params2)
            stopped2 = truncation(c2.stop_reason)
            if not stopped2 or len(c2.text.strip()) > len(text):
                text, stopped = c2.text.strip(), stopped2
        out = {"heading": sec.get("heading", ""), "text": text}
        if stopped:
            out["stopped"] = stopped
        return out

    def _finish_writing(self, job: Job, review_id: int, state: dict, meta: dict, words: int) -> dict:
        # Belege aus Blättern mit gedruckten Seitenzahlen sind schon richtig (nicht mehr umrechnen)
        state["_seiten_ok"] = sorted(set(state.get("_seiten_ok") or [])
                                     | {k for k, m in meta.items() if self._has_page_labels(m["lib"], k)})
        self.store.update_review_state(review_id, state)
        # Seiten für Belege ohne Seitenangabe gleich jetzt suchen (sonst beim ersten Anzeigen)
        job.update(message="Seiten der Belege suchen")
        try:
            self.locate_pages(review_id)
        except Exception as e:  # noqa: BLE001
            log.warning("Seiten der Belege nicht gefunden: %s", e)
        check = self.check(review_id)
        msg = (f"{words} Wörter geschrieben; {len(check['unknown_keys'])} unbekannte Belege, "
               f"{len(check['unverified_quotes'])} ungeprüfte Zitate")
        if check["incomplete_sections"]:
            msg += f"; {len(check['incomplete_sections'])} unvollständige Abschnitte"
        job.update(phase="Fertig", message=msg)
        return check

    def write(self, job: Job, review_id: int) -> dict:
        review, state, meta, model, effort, system, outline_text = self._write_context(review_id, job)
        outline = state["outline"]
        sections: list[dict] = []
        job.update(phase="Schreiben", total=len(outline["sections"]), done=0)
        for sec in outline["sections"]:
            job.check()
            job.update(message=f"Abschnitt: {sec.get('heading', '')}")
            sections.append(self._write_section(review, state, model, effort, system, outline_text, sec, sections))
            state["sections"] = sections
            self.store.update_review_state(review_id, state)
            job.step()
        state["step"] = "written"
        self._finish_writing(job, review_id, state, meta, sum(len(s["text"].split()) for s in sections))
        return {"sections": len(sections)}

    def rewrite_section(self, job: Job, review_id: int, index: int) -> dict:
        """Nur einen Abschnitt neu schreiben (z. B. einen abgeschnittenen); die übrigen bleiben, wie sie sind."""
        review, state, meta, model, effort, system, outline_text = self._write_context(review_id, job)
        outline_secs, sections = state["outline"]["sections"], list(state.get("sections") or [])
        if not 0 <= index < min(len(outline_secs), len(sections)):
            raise ValueError("Diesen Abschnitt gibt es nicht (mehr) – bitte den ganzen Text neu schreiben.")
        sec = outline_secs[index]
        job.update(phase="Schreiben", total=1, done=0, message=f"Abschnitt: {sec.get('heading', '')}")
        sections[index] = self._write_section(review, state, model, effort, system, outline_text, sec,
                                              sections[:index])
        state["sections"] = sections
        job.step()
        self._finish_writing(job, review_id, state, meta, len(sections[index]["text"].split()))
        return {"section": index}

    def long_sections(self, state: dict) -> list[dict]:
        """Abschnitte, die mehr als 20 % über ihrer geplanten Länge liegen."""
        planned = [s.get("words") for s in (state.get("outline") or {}).get("sections", [])]
        out = []
        for i, sec in enumerate(state.get("sections") or []):
            plan = int(planned[i] or 0) if i < len(planned) else 0
            words = count_words(sec.get("text", ""))
            if plan and words > LONG_FACTOR * plan:
                out.append({"index": i, "heading": sec.get("heading", ""), "words": words, "planned": plan})
        return out

    def shorten(self, job: Job, review_id: int, indexes: list[int] | None = None) -> dict:
        """Zu lange Abschnitte auf ihre geplante Länge kürzen lassen (ohne Auswertungsblätter: nur straffen, Belege und
        Zitate bleiben). Ohne `indexes` alle zu langen. Bricht die Ausgabe ab oder wird sie nicht kürzer, bleibt der
        Abschnitt, wie er war."""
        review, state, meta, model, effort, _system, _outline = self._write_context(review_id, job)
        sections = list(state.get("sections") or [])
        planned = [s.get("words") for s in state["outline"]["sections"]]
        todo = [x["index"] for x in self.long_sections(state)] if indexes is None else indexes
        todo = [i for i in todo if 0 <= i < min(len(sections), len(planned)) and planned[i]]
        if not todo:
            raise ValueError("Kein Abschnitt ist länger als geplant.")
        llm_cfg = self.engine.settings.llm
        job.update(phase="Kürzen", total=len(todo), done=0)
        before_words = sum(count_words(sections[i]["text"]) for i in todo)
        kept = []
        for i in todo:
            job.check()
            sec, limit = sections[i], int(planned[i])
            job.update(message=f"Abschnitt: {sec.get('heading', '')}")
            old = sec["text"]
            params = GenParams(max_tokens=max(4000, min(llm_cfg.max_output_tokens, limit * 4 + 4000)),
                               temperature=llm_cfg.temperature, effort=effort)
            prompt = SHORTEN_PROMPT.format(words=count_words(old), limit=limit, text=old)
            c = model.complete(SHORTEN_SYSTEM, [ChatMessage("user", prompt)], params)
            stopped = truncation(c.stop_reason)
            if stopped:
                cap = max(llm_cfg.max_output_tokens, params.max_tokens * 2)
                params2, prompt2 = retry_after_truncation(stopped, params, prompt, cap)
                c = model.complete(SHORTEN_SYSTEM, [ChatMessage("user", prompt2)], params2)
                stopped = truncation(c.stop_reason)
            text = c.text.strip()
            first = old.lstrip().splitlines()[0] if old.strip() else ""
            if text and first.startswith("#") and not text.startswith("#"):
                text = f"{first}\n\n{text}"  # Überschrift weggelassen: wieder davor
            if stopped or not text or count_words(text) >= count_words(old):
                kept.append(sec.get("heading", ""))
            else:
                sections[i] = {"heading": sec.get("heading", ""), "text": text}
                state["sections"] = sections
                self.store.update_review_state(review_id, state)
            job.step()
        state["sections"] = sections
        after_words = sum(count_words(sections[i]["text"]) for i in todo)
        check = self._finish_writing(job, review_id, state, meta, after_words)
        msg = f"Gekürzt: {before_words} → {after_words} Wörter"
        if kept:
            msg += f"; unverändert: {', '.join(kept)}"
        job.update(phase="Fertig", message=msg)
        return {"sections": len(todo) - len(kept), "kept": kept, "check": check}

    # ------------------------------------------------------------------------------
    # Schritt 4: Kontrolle & Ausgabe
    # ------------------------------------------------------------------------------
    _CITE = re.compile(r"\[(@[^\]]+)\]")
    # Deutsche („…“), englische (“…”) und gerade Anführungszeichen sowie Guillemets
    _QUOTE = re.compile(r"[„“\"«»]([^„“”\"«»]{25,600})[“”\"«»]")

    def check(self, review_id: int) -> dict:
        review = self.store.get_review(review_id)
        state = review["state"]
        text = "\n\n".join(s["text"] for s in state.get("sections", []))
        docs = {d["item_key"]: d for d in self.store.review_docs(review_id) if d["included"]}
        used: set[str] = set()
        unknown: list[str] = []
        for m in self._CITE.finditer(text):
            for key, _page in parse_citation(m.group(1)):
                if key in docs:
                    used.add(key)
                elif key not in unknown:
                    unknown.append(key)
        # Originaltext je Dokument (Abschnitte ohne Überlappung zusammengesetzt)
        doc_texts: dict[str, str] = {}
        for key, d in docs.items():
            by_att: dict[str, list[str]] = {}
            for r in self.store.document_chunks(d["lib"], key):
                by_att.setdefault(r["att_key"], []).append(r["text"])
            doc_texts[key] = _norm(" ".join(_merge_overlapping(t) for t in by_att.values() if t))
        verified, unverified = [], []
        for m in self._QUOTE.finditer(text):
            quote = m.group(1).strip()
            nq = _norm(quote)
            if len(nq) < 20:
                continue
            after = text[m.end(): m.end() + 200]
            cm = self._CITE.search(after)
            keys = [k for k, _ in parse_citation(cm.group(1))] if cm else []
            candidates = [k for k in keys if k in doc_texts] or list(doc_texts)
            if any(nq in doc_texts[k] for k in candidates):
                verified.append(quote[:120])
            else:
                unverified.append({"quote": quote[:300], "keys": keys})
        planned = [s.get("words") for s in (state.get("outline") or {}).get("sections", [])]
        incomplete = []
        for i, sec in enumerate(state.get("sections", [])):
            reasons = incomplete_reasons(sec, planned[i] if i < len(planned) else None)
            if reasons:
                incomplete.append({"index": i, "heading": sec.get("heading", ""), "reasons": reasons,
                                   "words": len(sec.get("text", "").split()),
                                   "planned": planned[i] if i < len(planned) else None})
        # Belege auf Texte, die in Zotero gelöscht wurden und keine Kopie mehr haben (references.repair stellt die
        # übrigen beim Öffnen um)
        cited_items = self._items((docs[k]["lib"], k) for k in used)
        removed = [{"key": k, "lib": docs[k]["lib"],
                    "citation": author_year(cited_items[(docs[k]["lib"], k)]) if (docs[k]["lib"], k) in cited_items else k,
                    "title": (cited_items.get((docs[k]["lib"], k)) or {}).get("title", "")}
                   for k in sorted(used) if (cited_items.get((docs[k]["lib"], k)) or {"removed": True}).get("removed")]
        result = {
            "words": count_words(text),
            "planned_words": sum(int(p or 0) for p in planned),
            "long_sections": self.long_sections(state),
            "cited_docs": len(used),
            "uncited_docs": [{"key": k, "lib": docs[k]["lib"]} for k in docs if k not in used],
            "unknown_keys": unknown,
            "removed_docs": removed,
            "verified_quotes": len(verified),
            "unverified_quotes": unverified,
            "incomplete_sections": incomplete,
            "checked_at": time.time(),
        }
        state["check"] = result
        self.store.update_review_state(review_id, state)
        return result

    def render(self, review_id: int, with_links: bool = True, body_only: bool = False,
               link_target: str | None = None, cites: list[dict] | None = None) -> str:
        """Markdown mit aufgelösten Belegen (Autor Jahr, S. x) und Literaturverzeichnis.
        link_target: „pdf“ (Seite in der PDF, sonst Eintrag), „item“ (immer der Eintrag in Zotero) oder „dialog“
        (für die Programmoberfläche: Link #cite-N; cites erhält je Beleg beide Ziele, die Oberfläche fragt nach)."""
        try:  # Seitenangaben aus der Zeit vor der Seitenzahl-Erkennung umstellen (je Text, sobald neu indexiert)
            self.ensure_review_pages(review_id)
        except Exception as e:  # noqa: BLE001
            log.warning("Seitenangaben nicht umgestellt: %s", e)
        review = self.store.get_review(review_id)
        state = review["state"]
        docs = {d["item_key"]: d for d in self.store.review_docs(review_id)}
        items = self._items((d["lib"], d["item_key"]) for d in docs.values())
        used: list[str] = []
        target = link_target or self.engine.settings.review.link_target
        if target == "dialog" and cites is None:
            cites = []
        title = (state.get("outline") or {}).get("title") or review["title"]
        text = latex_to_text("\n\n".join(s["text"] for s in state.get("sections", [])))
        lang = state.get("language") or "de"
        page_prefix = "S." if lang == "de" else "p."  # Seitenangabe in der Sprache des Forschungsstands
        # Belege ohne Seitenangabe: Link auf die Seite, auf der die belegte Aussage steht (im Text bleibt „Autor Jahr“)
        located: dict[str, int | None] = {}
        if with_links and target in ("pdf", "dialog"):
            try:
                located = self.locate_pages(review_id, text)
            except Exception as e:  # noqa: BLE001 – dann öffnet der Link die PDF am Anfang
                log.warning("Seiten der Belege nicht gefunden: %s", e)

        def resolve(m: re.Match) -> str:
            out = []
            parsed = parse_citation(m.group(1))
            if not parsed:
                return m.group(0)
            ctx = None
            for i, (key, page) in enumerate(parsed):
                d = docs.get(key)
                if not d:
                    out.append(f"[?{key}]")
                    continue
                if key not in used:
                    used.append(key)
                it = items.get((d["lib"], key), {})
                no_page = page == NO_PAGE
                # „Shin et al. [@KEY]“: der Name steht schon im Satz – der Beleg nennt nur Jahr und Seite
                who = str(it.get("year") or "o. J.") if i == 0 and named_before(text[:m.start()], it) else author_year(it)
                label = who + (f", {NO_PAGE}" if no_page else f", {page_prefix} {page}" if page else "")
                if not with_links:
                    out.append(label)
                    continue
                pdf = self._pdf_attachment(d["lib"], key)
                idx = None
                if pdf and target in ("pdf", "dialog"):
                    if page and not no_page:
                        idx = self._page_index(d["lib"], key, page)
                    else:  # ohne (gedruckte) Seitenangabe: Fundstelle des Zitats bzw. der belegten Aussage
                        ctx = ctx if ctx is not None else self._cite_context(text, m.start())
                        idx = located.get(self._page_ref(key, ctx))
                select = zotero_select_url(d["lib"], key)
                pdf_url = zotero_open_pdf_url(d["lib"], pdf["key"], idx) if pdf else None
                if target == "dialog":
                    cites.append({"label": label, "citation": author_year(it), "title": it.get("title") or "",
                                  "select": select, "pdf": pdf_url, "page": "" if no_page else page, "no_page": no_page,
                                  "pdf_page": idx + 1 if idx is not None else None,
                                  "located": bool(idx is not None and (not page or no_page)),
                                  "removed": bool(it.get("removed"))})
                    out.append(f"[{label}](#cite-{len(cites) - 1})")
                else:
                    out.append(f"[{label}]({pdf_url if target == 'pdf' and pdf_url else select})")
            return "(" + "; ".join(out) + ")"

        body = self._CITE.sub(resolve, text)
        if body_only:
            return body
        refs = self._bibliography(used, docs, items)
        heading ={"de": "Literatur", "en": "References", "fr": "Bibliographie", "it": "Bibliografia"}.get(lang, "Literatur")
        return f"# {title}\n\n{body}\n\n## {heading}\n\n{refs}\n\n{self.method_appendix(review)}"

    def method_appendix(self, review: dict) -> str:
        """Dokumentation der Suche (wie bei Datenbankrecherchen): Frage, Korpora, Suchanfragen mit Treffern.
        In der Sprache des Forschungsstands (fehlt eine Übersetzung, deutsch)."""
        state = review["state"]
        lang = state.get("language") or "de"
        filters = state.get("filters") or {}
        ids = filters.get("corpus_ids") or ([filters["corpus_id"]] if filters.get("corpus_id") else [])
        names = [c["name"] for c in (self.store.corpus(int(i)) for i in ids) if c]
        when = time.strftime("%d.%m.%Y", time.localtime(state["searched_at"])) if state.get("searched_at") else "–"
        docs = self.store.review_docs(review["id"])
        what = ", ".join(names) if names else tr("alle indexierten Texte", lang)
        included = sum(1 for d in docs if d["included"])
        question = review["question"]
        searched = f"Durchsucht: {what} (Zotero-Bibliothek, hybride Bedeutungs- und Stichwortsuche, Zotivity)"
        when_line = (f"Suche am: {when}; {len(docs)} Kandidaten, davon {included} einbezogen "
                     "(Vorauswahl durch Sprachmodell, geprüft und bestätigt)")
        lines = ["## " + tr("Anhang: Methode der Literatursuche", lang), "",
                 "- " + tr(f"Forschungsfrage: {question}", lang),
                 "- " + tr(searched, lang),
                 "- " + tr(when_line, lang),
                 "",
                 f"| {tr('Suchanfrage', lang)} | {tr('gefundene Texte', lang)} | {tr('nur durch diese Anfrage', lang)} |",
                 "|---|---:|---:|"]
        stats = {s["query"]: s for s in state.get("query_stats") or []}
        for q in state.get("queries") or []:
            s = stats.get(q, {})
            lines.append(f"| {q.replace('|', '/')} | {s.get('docs', '–')} | {s.get('unique', '–')} |")
        return "\n".join(lines) + "\n"

    def _bibliography(self, keys: list[str], docs: dict, items: dict) -> str:
        if not keys:
            return ""
        try:
            zot = self.engine.zotero()
            by_lib: dict[str, list[str]] = {}
            for k in keys:
                by_lib.setdefault(docs[k]["lib"], []).append(k)
            entries = []
            for lib, ks in by_lib.items():
                for i in range(0, len(ks), 50):
                    r = zot._request("GET", f"/api/{lib}/items",
                                     params={"itemKey": ",".join(ks[i:i + 50]), "format": "bib", "style": "apa"})
                    if r.status_code == 200:
                        for div in re.findall(r'<div class="csl-entry"[^>]*>(.*?)</div>', r.text, re.S):
                            entries.append(strip_bidi(html.unescape(re.sub(r"<[^>]+>", "", div))).strip())
            if entries:
                return "\n".join(f"- {e}" for e in sorted(entries))
        except Exception as e:  # noqa: BLE001
            log.info("Literaturverzeichnis über Zotero nicht möglich: %s", e)
        lines = []
        for k in keys:
            it = items.get((docs[k]["lib"], k), {})
            lines.append(f"- {author_year(it)}: {it.get('title', '')}. {it.get('publication', '')}".rstrip(". ") + ".")
        return "\n".join(sorted(lines))

    def save_to_zotero(self, review_id: int) -> str:
        review = self.store.get_review(review_id)
        state = review["state"]
        md = self.render(review_id, with_links=True)
        zot = self.engine.zotero()
        lib = state.get("collection_lib", "users/0")
        note_key = zot.create_note(lib, None, md_to_html(md), tags=["Zotivity-Forschungsstand"])
        if state.get("collection_key"):
            zot.add_to_collection(lib, state["collection_key"], [note_key])
        state["note_key"] = note_key
        self.store.update_review_state(review_id, state)
        return note_key
