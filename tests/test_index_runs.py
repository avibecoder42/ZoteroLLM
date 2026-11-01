"""Verlauf der Indexierläufe, Übersicht des Index und feste Projektfarben."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_indexing_search import build_library, run_index

from zotivity.index.indexer import Indexer
from zotivity.index.store import PROJECT_COLORS, Store
from zotivity.jobs import Job, JobCancelled

H = {"X-Zotivity": "1"}


def test_runs_are_recorded_only_with_work(zengine, fake_zotero):
    build_library(fake_zotero)
    _, job = run_index(zengine, trigger="background")
    runs = zengine.store.index_runs()
    assert len(runs) == 1
    r = runs[0]
    assert r["status"] == "done" and r["trigger"] == "background" and r["docs_done"] == 2 and r["indexed"] == 2
    assert r["chunks"] > 0 and r["finished_at"] >= r["started_at"] and not r["dismissed"]
    assert job.counters["run_id"] == r["id"] and job.counters["problems"] == 0 and job.counters["trigger"] == "background"
    detail = zengine.store.index_run(r["id"])
    assert {d["parent"] for d in detail["docs"]} == {"ITEMA001", "ITEMB001"} and detail["log"]
    # Zweiter Lauf ohne Arbeit: kein neuer Eintrag, aber „zuletzt geprüft“
    checked = float(zengine.store.get_meta("index_checked_at"))
    run_index(zengine)
    assert len(zengine.store.index_runs()) == 1
    assert float(zengine.store.get_meta("index_checked_at")) >= checked
    zengine.store.dismiss_index_run(r["id"])
    assert zengine.store.index_runs()[0]["dismissed"] == 1


def test_cancelled_and_stage_runs(zengine, fake_zotero):
    build_library(fake_zotero)

    class CancelSecond(Job):
        def __init__(self):
            super().__init__("index", "test")
            self.calls = 0

        def check(self):
            # Abbruch, sobald der zweite Text beginnt
            if self.counters.get("docs_done") == 1:
                raise JobCancelled()

    with pytest.raises(JobCancelled):
        Indexer(zengine).run(CancelSecond())
    r = zengine.store.index_runs()[0]
    assert r["status"] == "cancelled" and r["docs_done"] == 1 and r["docs_total"] == 2


def test_stage_run(zengine, fake_zotero):
    build_library(fake_zotero)
    _, job = run_index(zengine, max_docs=1)  # Etappe: höchstens ein Text pro Lauf
    r = zengine.store.index_runs()[0]
    assert r["status"] == "stage" and r["docs_done"] == 1 and r["stopped"].startswith("Etappe beendet")
    assert job.counters["stopped"] == r["stopped"]


def test_overview_and_runs_api(zengine, fake_zotero, monkeypatch):
    build_library(fake_zotero)
    run_index(zengine)
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        o = c.get("/api/index/overview").json()
        assert o["corpora"] == 1 and o["stats"]["indexed"] == 2 and o["stats"]["pending"] == 0
        assert o["checked_at"] and o["mode"] == "manual" and o["next_check_at"] is None
        c.put("/api/settings", json={"indexing": {"mode": "background", "interval_minutes": 15}}, headers=H)
        o = c.get("/api/index/overview").json()
        assert o["next_check_at"] is not None
        runs = c.get("/api/index/runs").json()["runs"]
        assert len(runs) == 1 and runs[0]["indexed"] == 2
        d = c.get(f"/api/index/runs/{runs[0]['id']}").json()
        assert len(d["docs"]) == 2 and d["docs"][0]["select"].startswith("zotero://select/")
        assert c.post(f"/api/index/runs/{runs[0]['id']}/dismiss", headers=H).status_code == 200
        assert c.get("/api/index/runs").json()["runs"][0]["dismissed"] == 1
        assert c.get("/api/index/runs/999").status_code == 404


def test_last_indexed_corpus(zengine, fake_zotero, monkeypatch):
    """Vorauswahl rechts in der Ansicht Index: wann zuletzt Texte eines Korpus gelesen oder eingebettet wurden."""
    import time

    build_library(fake_zotero)
    ki = zengine.store.create_corpus("KI", ["users/0:COLA0001"])
    sa = zengine.store.create_corpus("Soziale Arbeit", ["users/0:COLB0002"])
    empty = zengine.store.create_corpus("Leer", [])
    run_index(zengine)
    time.sleep(0.05)
    zengine.store.mark_pending("users/0", ["ATTB0001"])
    run_index(zengine, corpus_id=sa)  # nur „Soziale Arbeit“ wird neu gelesen
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        last = {k["id"]: k["last_indexed_at"] for k in c.get("/api/corpora").json()["corpora"]}
    assert last[sa] > last[ki] > 0 and last[empty] is None


def test_project_colors_are_stored(tmp_path):
    store = Store(tmp_path / "i.sqlite3")
    pid = store.create_project("Ohne Farbe")
    assert store.project(pid)["color"] == PROJECT_COLORS[pid % len(PROJECT_COLORS)]
    pid2 = store.create_project("Mit Farbe", color="#123456")
    assert store.project(pid2)["color"] == "#123456"
    store.close()
    # Ältere Datenbank: Projekt ohne gespeicherte Farbe bekommt beim Öffnen die bisher angezeigte (nach der ID)
    con = sqlite3.connect(tmp_path / "i.sqlite3")
    con.execute("UPDATE projects SET color='' WHERE id=?", (pid2,))
    con.commit()
    con.close()
    store = Store(tmp_path / "i.sqlite3")
    assert store.project(pid2)["color"] == PROJECT_COLORS[pid2 % len(PROJECT_COLORS)]
    store.close()


def test_reimport_keeps_color(engine):
    from zotivity.projects_io import export_project, import_project

    pid = engine.store.create_project("Farbig")
    color = engine.store.project(pid)["color"]
    _, data = export_project(engine, pid)
    for _ in range(3):  # neue IDs – die Farbe muss trotzdem gleich bleiben
        new = import_project(engine, data)
        assert engine.store.project(new["project_id"])["color"] == color
