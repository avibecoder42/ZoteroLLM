"""Volltextprüfung, Flussdiagramm, Reviewende, Suchdatum beim Import und KI-Bericht (PRISMA 2020, Items 5–8, 16a):
Die Prüfung läuft auch ganz ohne Volltexte, Zahlen im Bericht kommen nur aus den Fakten, in Zotero wird nichts gelöscht."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from research_fakes import MemoryKeyStore

from zotivity.research import ai as ai_mod
from zotivity.research import protocol
from zotivity.research.api import install
from zotivity.research.errors import ZoteroWriteRefused
from zotivity.research.ports import MY_LIBRARY, is_fulltext
from zotivity.research.service import SET_ASIDE_TAG, ResearchConfig, ResearchService
from zotivity.research_adapters import prefer_local_zotero

RIS = "\n".join(
    line for i in range(1, 7) for line in (f"TY  - JOUR", f"TI  - Study number {i} on online aggression among teens",
                                           f"DO  - 10.1000/x{i}", f"PY  - 202{i}", "ER  - ", ""))


class Zot:
    """Attrappe mit Anhängen und Schlagwörtern."""

    backend = "local"

    def __init__(self):
        self.files, self.calls, self.down = set(), [], False
        self.n = 0

    def status(self):
        return {"ok": not self.down, "message": ""}

    def can_write(self, lib=MY_LIBRARY):
        return True

    def collections(self, lib):
        return [{"key": "COLL", "name": "Rollen", "parent": None}]

    def create_items(self, lib, items):
        out = []
        for _ in items:
            self.n += 1
            out.append({"key": f"ITEM{self.n}"})
        return out

    def add_to_collection(self, lib, key, items):
        return len(items)

    def has_fulltext(self, lib, key):
        if self.down:
            from zotivity.research.errors import SourceError

            raise SourceError("Zotero ist nicht erreichbar.")
        self.calls.append(("file", key))
        return key in self.files

    def set_aside(self, lib, key, collections, tag):
        self.calls.append(("aside", key, tuple(collections), tag))


@pytest.fixture
def zot():
    return Zot()


@pytest.fixture
def svc(store, sim, zot):
    return ResearchService(store, MemoryKeyStore(), {"local": zot}, http=sim.http(), sleep=lambda s: None,
                           config=ResearchConfig(default_backend="local"))


def prepared(svc):
    """Sechs Treffer: vier eingeschlossen und übergeben, einer ausgeschlossen, einer offen."""
    p = svc.create_project({"title": "T", "question": "Frage", "criteria_out": "Tierstudie\nkein Volltext",
                            "folder_map": [{"slot": 1, "label": "Rollen", "path": "Rollen"}]})
    pid = p["id"]
    svc.update_project(pid, {"prefilters": []})
    svc.import_ris(pid, "a.ris", RIS, "psycinfo", "Ovid", "aggression", 6, searched_on="2026-10-30")
    ids = [it["id"] for it in svc.pool(pid)["items"]]
    for rid in ids[:4]:
        svc.decide(pid, rid, "include", folder=1)
    svc.decide(pid, ids[4], "exclude", reason="Tierstudie")
    svc.export(pid, confirm=True, crossref=False)
    return pid, ids


def test_new_projects_use_local_zotero_and_old_ones_move(svc, store):
    assert svc.create_project({"title": "Neu"})["zotero_backend"] == "local"
    old = store.create_project({"title": "Alt", "zotero_backend": "web"})
    assert prefer_local_zotero(svc, MemoryKeyStore(zotero_web="KEY")) == 0
    assert store.project(old["id"])["zotero_backend"] == "web"  # mit Schlüssel bleibt die bewusste Wahl
    assert prefer_local_zotero(svc, MemoryKeyStore()) == 1
    assert store.project(old["id"])["zotero_backend"] == "local"


def test_reviewers_are_limited_and_recorded(svc):
    pid = svc.create_project({"title": "T"})["id"]
    s = svc.update_project(pid, {"settings": {"reviewers": [" Ana  B ", "Ben", "Ana B", "", "Cem", "Dan"], "current_reviewer": "Ben"}})["settings"]
    assert s["reviewers"] == ["Ana B", "Ben", "Cem"] and s["current_reviewer"] == "Ben"
    assert svc.update_project(pid, {"settings": {"reviewers": ["Ana B"]}})["settings"]["current_reviewer"] == ""
    svc.update_project(pid, {"settings": {"reviewers": ["Ana B", "Ben"], "current_reviewer": "Ben", "selection_note": "Uneinigkeit im Gespräch gelöst"}})
    svc.import_ris(pid, "a.ris", RIS, "psycinfo")
    ids = [it["id"] for it in svc.pool(pid)["items"]]
    assert svc.decide(pid, ids[0], "exclude")["by"] == "Ben"
    assert svc.decide(pid, ids[1], "exclude", by="Ana B")["by"] == "Ana B"
    svc.decide_bulk(pid, [{"record_id": ids[2], "status": "exclude"}])
    md = protocol.markdown(svc, pid)
    assert "Beteiligte Personen: Ana B, Ben." in md and "Entscheide je Person:" in md and "Ben 2" in md
    assert "ein unabhängiges Doppel-Screening erfasst die App nicht" in md and "Uneinigkeit im Gespräch gelöst" in md


def test_import_keeps_the_search_date(svc):
    pid = svc.create_project({"title": "T"})["id"]
    svc.import_ris(pid, "a.ris", RIS, "psycinfo", searched_on="2026-10-30")
    assert svc.runs(pid)[0]["searched_on"] == "2026-10-30"
    assert "| 2026-10-30 | " in protocol.markdown(svc, pid)
    with pytest.raises(Exception, match="JJJJ-MM-TT"):
        svc.import_ris(pid, "b.ris", RIS, "psycinfo", searched_on="30.10.2026")


def test_is_fulltext_counts_documents_not_snapshots():
    assert is_fulltext({"data": {"itemType": "attachment", "contentType": "application/pdf"}})
    assert not is_fulltext({"data": {"itemType": "attachment", "contentType": "text/html"}})
    assert not is_fulltext({"data": {"itemType": "note"}})


def test_fulltext_without_files_is_the_normal_case(svc, zot):
    pid, ids = prepared(svc)
    r = svc.fulltext(pid)
    assert r["counts"] == {"missing": 4} and len(r["items"]) == 4 and not r["zotero_error"]
    # Ein PDF kommt dazu: beim nächsten Öffnen erkannt; bekannte werden nicht jedes Mal neu gefragt
    key = r["items"][0]["zotero_key"]
    zot.files.add(key)
    r = svc.fulltext(pid)
    assert r["counts"] == {"available": 1, "missing": 3}
    zot.calls.clear()
    svc.fulltext(pid)
    assert len(zot.calls) == 3 and ("file", key) not in zot.calls
    svc.fulltext(pid, refresh="all")
    assert ("file", key) in zot.calls


def test_fulltext_works_with_zotero_closed(svc, zot):
    pid, ids = prepared(svc)
    zot.files.add(svc.fulltext(pid)["items"][0]["zotero_key"])
    svc.fulltext(pid)
    zot.down = True
    r = svc.fulltext(pid, refresh="all")
    assert "nicht erreichbar" in r["zotero_error"] and r["counts"]["available"] == 1  # zuletzt bekannter Stand
    r = svc.set_fulltext(pid, [ids[1]], "not_retrieved", "Fernleihe abgelehnt")
    assert r["counts"]["not_retrieved"] == 1


def test_flow_adds_up_and_says_when_fulltext_is_missing(svc):
    pid, ids = prepared(svc)
    f = protocol.flow(svc, pid)
    assert f["identified"] == 6 and f["duplicates"] == 0 and f["pool"] == 6 and f["screened"] == 6
    assert f["excluded"] == 1 and f["open"] == 1 and f["sought"] == 4 and not f["fulltext_used"] and f["included"] == 0
    assert f["screening_reasons"] == {"Tierstudie": 1}
    svg = svc.flow(pid)["svg"]
    assert svg.startswith("<svg") and "Volltextprüfung nicht erfasst" in svg and "Für die Volltextprüfung ausgewählt: 4" in svg
    assert "Nicht erfasst: Die Auswahl ist bis zum Titel-/Abstract-Screening dokumentiert (4 Arbeiten ausgewählt)." in protocol.markdown(svc, pid)

    svc.set_fulltext(pid, [ids[0]], "include")
    svc.set_fulltext(pid, [ids[1]], "exclude", "falsche Population")
    svc.set_fulltext(pid, [ids[2]], "not_retrieved", "nicht greifbar")
    f = protocol.flow(svc, pid)
    assert f["fulltext_used"] and (f["included"], f["fulltext_excluded"], f["not_retrieved"], f["missing"], f["assessed"]) == (1, 1, 1, 1, 2)
    assert f["fulltext_reasons"] == {"falsche Population": 1}
    svg = svc.flow(pid, "en")["svg"]
    assert "Reports assessed: 2" in svg and "falsche Population: 1" in svg and "Included: 1" in svg
    assert "geprüft: 2; dabei ausgeschlossen: 1; eingeschlossen: 1" in protocol.markdown(svc, pid)
    # Zurücksetzen löscht den Stand
    svc.set_fulltext(pid, [ids[0], ids[1], ids[2]], "")
    assert not protocol.flow(svc, pid)["fulltext_used"]


def test_flow_escapes_user_text(svc):
    pid, ids = prepared(svc)
    svc.set_fulltext(pid, [ids[0]], "exclude", "<b>&böse")
    assert "&lt;b&gt;&amp;böse" in svc.flow(pid)["svg"] and "<b>" not in svc.flow(pid)["svg"]


def test_set_aside_needs_confirmation_and_never_deletes(svc, zot):
    pid, ids = prepared(svc)
    svc.set_fulltext(pid, [ids[1]], "exclude", "falsche Population")
    svc.set_fulltext(pid, [ids[0]], "include")
    assert svc.fulltext(pid, refresh="")["to_set_aside"] == 1
    with pytest.raises(ZoteroWriteRefused):
        svc.fulltext_set_aside(pid)
    r = svc.fulltext_set_aside(pid, confirm=True)
    assert r["done"] == 1 and not r["failed"]
    aside = [c for c in zot.calls if c[0] == "aside"]
    assert len(aside) == 1 and aside[0][2] == ("COLL",) and aside[0][3] == SET_ASIDE_TAG
    # Nur einmal
    assert svc.fulltext(pid, refresh="")["to_set_aside"] == 0
    assert svc.fulltext_set_aside(pid, confirm=True)["done"] == 0


class Chat:
    label = "Fake"
    model = "fake"
    usage = {}

    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def complete_json(self, system, prompt, schema=None):
        self.seen.append((system, prompt, schema))
        return self.answer


def test_report_checks_numbers_against_the_facts(store, sim, zot):
    chat = Chat({"methods": "Gesucht wurde in PsycInfo am 30. Oktober 2026.", "results": "Von 6 Datensätzen blieben 4; das sind 66,6 %. [fehlt: Förderung]",
                 "note": "Förderung fehlt."})
    svc = ResearchService(store, MemoryKeyStore(), {"local": zot}, http=sim.http(), chat=chat, sleep=lambda s: None,
                          config=ResearchConfig(default_backend="local"))
    pid, _ = prepared(svc)
    r = svc.ai_report(pid, "de")
    assert r["warnings"] == ["66"]  # die ausgerechnete Prozentzahl fällt auf; Datum und Zahlen aus den Fakten nicht
    system, facts, schema = chat.seen[0]
    assert schema is ai_mod.REPORT_SCHEMA and "[fehlt:" in system and "Deutsch" in system
    assert "RIS-Import aus der Datenbank, Suchdatum 2026-10-30" in facts
    assert "eine Volltextprüfung ist nicht dokumentiert" in facts and "ein unabhängiges Doppel-Screening erfasst die App nicht" in facts
    # Bleibt beim Projekt, auch nach einem Neustart
    assert svc.get_project(pid)["settings"]["report_last"]["methods"].startswith("Gesucht wurde")
    svc.ai_report(pid, "en")
    assert "English" in chat.seen[1][0]
    assert ai_mod.numbers_in("1'250 und 1 250 und 1250, 30, 2026") == {"1250", "30", "2026"}
    assert svc.ai_estimate(pid, "report")["input"] > 100


def test_api_routes(svc, zot):
    pid, ids = prepared(svc)
    app = FastAPI()
    install(app, svc)
    c = TestClient(app)
    assert c.get(f"/api/research/projects/{pid}/fulltext").json()["counts"] == {"missing": 4}
    r = c.post(f"/api/research/projects/{pid}/fulltext", json={"record_ids": [ids[0]], "status": "include"})
    assert r.json()["counts"]["include"] == 1
    assert c.post(f"/api/research/projects/{pid}/fulltext", json={"record_ids": [ids[0]], "status": "falsch"}).status_code == 400
    assert c.post(f"/api/research/projects/{pid}/fulltext/set-aside", json={}).status_code == 409
    flow = c.get(f"/api/research/projects/{pid}/flow?lang=en").json()
    assert flow["flow"]["included"] == 1 and "Included: 1" in flow["svg"]
    assert c.post(f"/api/research/projects/{pid}/ai/report", json={}).status_code == 400  # ohne Sprachmodell


def test_no_config_ini_hints_left():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "zotivity"
    for f in list(root.rglob("*.py")) + list((root / "server" / "static" / "js").rglob("*.js")):
        assert "config.ini" not in f.read_text(encoding="utf-8"), f
