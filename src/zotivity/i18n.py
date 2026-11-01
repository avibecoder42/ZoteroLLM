"""Übersetzung der Meldungen des Dienstes für die Oberfläche.

Ausgangssprache ist Deutsch. Die Wörterbücher liegen in ``zotivity/locales/<code>.py`` (Variable ``MESSAGES``):
deutscher Text oder deutsche Vorlage mit ``{platzhaltern}`` → Übersetzung. Übersetzt wird an den Ausgängen zur
Oberfläche (Fehlerantworten, Aufträge, Einrichtung, Status, Ereignisse beim Fragen); Quelltext und Protokolle bleiben
deutsch. Zusammengesetzte Meldungen („Teil: Rest“, „Teil – Rest“) werden stückweise übersetzt.

Neue Sprache: ``locales/<code>.py`` mit ``MESSAGES = {...}`` anlegen (und das Wörterbuch der Oberfläche in
``server/static/js/i18n``); fehlende Einträge erscheinen deutsch.
"""

from __future__ import annotations

import importlib
import re
from functools import lru_cache
from typing import Any

_language = "de"
# Platzhalter, deren Werte selbst Meldungen sind (z. B. Fehlertexte) und mitübersetzt werden
_NESTED = {"msg", "e", "error", "detail", "hint", "reason", "step"}


def set_language(code: str | None) -> None:
    global _language
    _language = (code or "de").lower()


def language() -> str:
    return _language


@lru_cache(maxsize=None)
def _catalog(lang: str) -> tuple[dict[str, str], list[tuple[re.Pattern, str]]]:
    try:
        messages: dict[str, str] = importlib.import_module(f"zotivity.locales.{lang}").MESSAGES
    except (ImportError, AttributeError):
        return {}, []
    exact = {k: v for k, v in messages.items() if not re.search(r"\{\w+\}", k)}
    patterns = []
    for k, v in messages.items():
        if re.search(r"\{\w+\}", k):
            rx = re.sub(r"\\\{(\w+)\\\}", lambda m: f"(?P<{m.group(1)}>.+?)", re.escape(k))
            patterns.append((re.compile(f"^{rx}$", re.S), v))
    # Lange (spezifische) Vorlagen zuerst, damit „Fehler bei „{title}“: {msg}“ vor „{a}: {b}“ greift
    patterns.sort(key=lambda p: -len(p[0].pattern))
    return exact, patterns


@lru_cache(maxsize=8192)
def _translate(text: str, lang: str) -> str:
    exact, patterns = _catalog(lang)
    if text in exact:
        return exact[text]
    stripped = text.strip()
    if stripped != text:
        inner = _translate(stripped, lang) if stripped else stripped
        return text.replace(stripped, inner) if inner != stripped else text
    for rx, template in patterns:
        m = rx.match(text)
        if m:
            values = {k: (_translate(v, lang) if k in _NESTED else v) for k, v in m.groupdict().items()}
            try:
                return template.format(**values)
            except (KeyError, IndexError):
                return text
    # Zusammengesetzt nur, wenn beide Teile bekannt sind (sonst würden z. B. Buchtitel „Suche: …“ angetastet)
    for sep in (": ", " – "):
        if sep in text:
            head, rest = text.split(sep, 1)
            a, b = _translate(head, lang), _translate(rest, lang)
            if a != head and b != rest:
                return a + sep + b
    return text


def tr_exact(text: Any, lang: str | None = None) -> Any:
    """Nur vollständig bekannte Texte übersetzen (für Felder, die auch Titel von Texten enthalten können)."""
    lang = lang or _language
    if lang == "de" or not isinstance(text, str):
        return text
    return _catalog(lang)[0].get(text, text)


def tr(text: Any, lang: str | None = None) -> Any:
    """Meldung in die Sprache der Oberfläche übersetzen (Nicht-Texte unverändert)."""
    lang = lang or _language
    if lang == "de" or not isinstance(text, str) or not text:
        return text
    return _translate(text, lang)


def tr_fields(d: dict, *keys: str) -> dict:
    """Kopie von d mit übersetzten Feldern."""
    out = dict(d)
    for k in keys:
        if k in out:
            out[k] = tr(out[k])
    return out
