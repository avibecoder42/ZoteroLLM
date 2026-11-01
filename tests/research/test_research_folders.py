"""Ordner: Sammlungsbaum, Anlegen nur nach Bestätigung, KI-Vorschlag für Untersammlungen."""

from __future__ import annotations

import pytest
from research_fakes import FakeZoteroPort, MemoryKeyStore
from test_research_ai import FakeChat

from zotivity.research.errors import ResearchError, ZoteroWriteRefused
from zotivity.research.service import ResearchService

COLS = [{"key": "A", "name": "test", "parent": None}, {"key": "B", "name": "Rollen", "parent": "A"},
        {"key": "C", "name": "alt", "parent": None}, {"key": "D", "name": "Bewältigung", "parent": "A"},
        {"key": "E", "name": "verwaist", "parent": "X"}]


def service(store, sim, chat=None, writable=True):
    zotero = FakeZoteroPort(collections=COLS, writable=writable)
    return ResearchService(store, MemoryKeyStore(), {"web": zotero}, http=sim.http(), chat=chat), zotero


def test_tree_sorted_with_paths(store, sim):
    svc, _ = service(store, sim)
    tree = svc.zotero_tree("web", "groups/1")["collections"]
    assert [n["name"] for n in tree] == ["alt", "test", "verwaist"]
    test = tree[1]
    assert [(n["name"], n["path"]) for n in test["children"]] == [("Bewältigung", "test/Bewältigung"), ("Rollen", "test/Rollen")]


def test_create_collections_needs_confirmation(store, sim):
    svc, zotero = service(store, sim)
    pid = svc.create_project({"title": "Ordner"})["id"]
    with pytest.raises(ZoteroWriteRefused):
        svc.create_collections(pid, ["test/Spass"])
    assert zotero.writes == []
    r = svc.create_collections(pid, ["test/Spass", "test/Rollen", "neu/unten", "test/Spass/"], confirm=True)
    assert r["created"] == ["neu", "neu/unten", "test/Spass"]  # vorhandene bleiben, doppelte einmal
    assert [w[2] for w in zotero.writes] == ["Spass", "neu", "unten"]

    ro, ro_zotero = service(store, sim, writable=False)
    with pytest.raises(ZoteroWriteRefused):
        ro.create_collections(pid, ["x"], confirm=True)
    assert ro_zotero.writes == []


def test_ai_folders_suggestion(store, sim):
    chat = FakeChat(lambda s, p, schema: {"folders": [
        {"name": "Rollen", "description": "gibt es schon"}, {"name": "Spass/Ernst", "description": "Grenze Spass und Ernst."},
        {"name": "Necken und Spass", "description": "doppelt"}, {"name": "Unterstützung", "description": "Hilfe holen."},
        {"name": "", "description": "leer"}], "note": ""})
    svc, zotero = service(store, sim, chat)
    pid = svc.create_project({"title": "Ordner"})["id"]
    with pytest.raises(ResearchError):
        svc.ai_folders(pid, "test")
    svc.update_project(pid, {"question": "Wie gehen Jugendliche mit Onlineaggressionen um?",
                             "folder_map": [{"slot": 1, "label": "Phänomene", "path": "test/Phänomene"}]})
    r = svc.ai_folders(pid, "test")
    assert r["existing"] == ["Bewältigung", "Rollen"]
    assert [f["name"] for f in r["folders"]] == ["Spass Ernst", "Necken und Spass", "Unterstützung"]
    system, prompt, schema = chat.calls[-1]
    assert "Übergeordnete Sammlung in Zotero: test" in prompt and "- Rollen" in prompt and "1: Phänomene" in prompt
    assert "angelegt wird erst nach ihrer Bestätigung" in system and schema["required"] == ["folders", "note"]
    assert zotero.writes == []  # ein Vorschlag legt nichts an
