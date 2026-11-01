"""Übersetzung der Meldungen des Dienstes und Vollständigkeit der Wörterbücher der Oberfläche."""

import re
from pathlib import Path

import pytest

from zotivity import i18n

STATIC = Path(__file__).resolve().parents[1] / "src" / "zotivity" / "server" / "static"


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("de")


def test_german_is_unchanged():
    i18n.set_language("de")
    assert i18n.tr("Fertig") == "Fertig"


@pytest.mark.parametrize("text, expected", [
    ("Fertig", "Done"),
    ("Indexierung: KI und Jugend", "Indexing: KI und Jugend"),
    ("Anthropic: Modell „claude-x“ nicht gefunden.", "Anthropic: model “claude-x” not found."),
    ("Embedding-Dienst nicht verfügbar: Ollama ist nicht erreichbar. Läuft Ollama?",
     "Embedding service not available: Ollama cannot be reached. Is Ollama running?"),
    ("Verbunden mit Zotero ", "Connected to Zotero "),
    ("Meine Bibliothek (1 von 3)", "My library (1 of 3)"),
    ("Etappe beendet: 50 Texte verarbeitet, 20 folgen im nächsten Lauf",
     "Stage finished: 50 texts processed, 20 follow in the next run"),
    ("Für Antworten ist Anthropic Claude eingestellt, aber dafür ist kein API-Schlüssel gespeichert. "
     "Unter Einstellungen → Sprachmodelle einen Schlüssel eintragen.",
     "Anthropic Claude is set for answers, but no API key is stored for it. Enter a key under Settings → Language models."),
])
def test_english_messages(english, text, expected):
    assert i18n.tr(text) == expected


def test_titles_are_not_touched(english):
    # Ein Buchtitel mit bekanntem Wort vor dem Doppelpunkt bleibt unverändert
    assert i18n.tr("Suche: Ein Buch über Jugendliche") == "Suche: Ein Buch über Jugendliche"
    assert i18n.tr_exact("Fertig") == "Done"
    assert i18n.tr_exact("Fertig: noch etwas") == "Fertig: noch etwas"


def test_unknown_language_falls_back():
    assert i18n.tr("Fertig", "xx") == "Fertig"


def test_job_dict_is_translated(english):
    from zotivity.jobs import Job

    job = Job("index", "Indexierung aller Korpora")
    job.update(phase="Abschluss", message="12 übrige Abschnitte",
               counters={"current": {"title": "Abstracts und übrige Abschnitte", "step": "Abschnitte werden eingebettet"}})
    d = job.as_dict()
    assert d["title"] == "Indexing all corpora"
    assert d["phase"] == "Finishing"
    assert d["message"] == "12 remaining passages"
    assert d["counters"]["current"] == {"title": "Abstracts and remaining passages", "step": "Embedding passages"}


def _ui_keys() -> set[str]:
    keys = set()
    for f in (STATIC / "js").rglob("*.js"):
        if "i18n" in f.parts:
            continue
        keys |= set(re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", f.read_text(encoding="utf-8")))
    return keys


def test_english_ui_dictionary_is_complete():
    en = (STATIC / "js" / "i18n" / "en.js").read_text(encoding="utf-8")
    have = set(re.findall(r"'((?:[^'\\]|\\.)*)':\s*'", en))
    missing = sorted(_ui_keys() - have)
    assert not missing, f"Ohne englische Übersetzung: {missing[:20]}"


def test_help_exists_for_every_language():
    langs = re.findall(r"code: '(\w+)'", (STATIC / "js" / "core" / "i18n.js").read_text(encoding="utf-8"))
    assert "de" in langs and "en" in langs
    for code in langs:
        md = (STATIC / "help" / f"{code}.md").read_text(encoding="utf-8")
        chapters = re.findall(r"^## ", md, re.M)
        assert len(chapters) >= 10, code
    de = (STATIC / "help" / "de.md").read_text(encoding="utf-8")
    en = (STATIC / "help" / "en.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^#{2,3} ", de, re.M)) == len(re.findall(r"^#{2,3} ", en, re.M))
