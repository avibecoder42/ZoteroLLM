"""Abgleich wie mit dem echten Zotero 10: Gruppenbibliotheken melden Version 0, haben oft keine Sammlungen."""

import os
import time

import pytest
from fakes import FakeZotero
from test_indexing_search import SOCIAL, TEEN

from zotivity import keystore
from zotivity.index.indexer import Indexer
from zotivity.jobs import Job
from zotivity.retrieval import Searcher
from zotivity.zotero import ZoteroClient

GROUP = "groups/1234567"


@pytest.fixture
def group(engine, tmp_path, monkeypatch):
    fz = FakeZotero(tmp_path / "storage", lib=GROUP, versioned=False, group_name="Projektgruppe")
    fz.add_item("RJYDLA5C", "Using Collaborative Documentation", "Smith", "2019")
    fz.add_pdf("ZAPZSESP", "RJYDLA5C", [SOCIAL * 6])
    fz.add_item("9D74I9KQ", "Implementing collaborative documentation", "Jones", "2021")
    fz.add_pdf("85E3AJ4C", "9D74I9KQ", [TEEN * 6])
    fz.add_note("NOTE0001", "9D74I9KQ")
    fz.add_link("LINK0001", "9D74I9KQ")
    client = ZoteroClient("http://127.0.0.1:23119", keystore=keystore.get_store(), transport=fz.transport())
    monkeypatch.setattr(engine, "zotero", lambda: client)
    return engine, fz


def run(engine, **kw):
    return Indexer(engine).run(Job("index", "t"), **kw)


def whole_group(engine):
    engine.store.create_corpus("Projektgruppe", [f"{GROUP}:*"])


def test_empty_selection_is_reported(group):
    engine, _ = group
    result = run(engine)
    assert result["nothing_selected"] is True and result["extracted"] == 0


def test_whole_library_selection_indexes_group(group):
    engine, fz = group
    whole_group(engine)
    result = run(engine)
    assert engine.store.library_state(GROUP)["name"] == "Projektgruppe"
    assert result["extracted"] == 2 and result["errors"] == 0
    st = engine.store.stats()
    # Link-Anhang ist "übersprungen", nicht dauerhaft "offen"; Notiz wird gar nicht gespeichert
    assert st["attachments_by_status"] == {"indexed": 2, "skipped": 1}
    hits = Searcher(engine).search("electronic information systems child welfare", k=3)
    assert hits[0].chunk["lib"] == GROUP and hits[0].chunk["item_key"] == "RJYDLA5C"


def test_followup_sync_with_version_zero_is_cheap_and_complete(group):
    engine, fz = group
    whole_group(engine)
    run(engine)
    first = fz.json_item_requests

    # Nichts geändert: kein erneutes Laden aller Einträge (Zotero würde sonst alle MD5 neu berechnen)
    result = run(engine)
    assert fz.json_item_requests == first and result["extracted"] == 0

    # Neuer Eintrag (Version bleibt 0) wird über die Schlüsselliste gefunden
    fz.add_item("NEWITEM1", "Neue Studie", "Neu", "2025")
    fz.add_pdf("NEWATT01", "NEWITEM1", ["Neue Befunde zur kollaborativen Dokumentation. " * 40])
    result = run(engine)
    assert result["synced"]["attachments"] == 1 and result["extracted"] == 1

    # Ersetzte PDF wird über Grösse/Änderungszeit erkannt
    pdf = fz.storage / "ZAPZSESP" / "ZAPZSESP.pdf"
    from fakes import make_pdf
    make_pdf(pdf, [SOCIAL * 3 + " Ganz neuer Abschnitt über Datenschutz. " * 30])
    os.utime(pdf, (time.time() + 10, time.time() + 10))
    result = run(engine)
    assert result["synced"]["changed_files"] == 1 and result["extracted"] == 1

    # Gelöschter Eintrag verschwindet
    del fz.items["NEWITEM1"], fz.items["NEWATT01"]
    result = run(engine)
    assert result["synced"]["deleted"] == 2 and engine.store.item(GROUP, "NEWITEM1") is None


def test_full_sync_refetches(group):
    engine, fz = group
    whole_group(engine)
    run(engine)
    before = fz.json_item_requests
    run(engine, full_sync=True)
    assert fz.json_item_requests > before
