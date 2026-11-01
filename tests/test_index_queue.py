"""Warteschlange der Indexierläufe, Modellwechsel mitten im Lauf und Farben der Titelleiste."""

import threading
import time

from fastapi.testclient import TestClient
from test_indexing_search import build_library, run_index
from test_model_switch import NamedHash

from zotivity.index.indexer import MODEL_SWITCHED, Indexer
from zotivity.jobs import JobManager, JobQueue
from zotivity.titlebar import apply, colorref

H = {"X-Zotivity": "1"}


def wait_until(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_queue_runs_in_order_and_can_be_reordered():
    jobs = JobManager()
    q = JobQueue(jobs, "index", "index")
    gate = threading.Event()
    order = []

    def blocker(job):
        gate.wait(5)
        order.append("erster")

    def named(name):
        return lambda job: order.append(name)

    assert "job" in q.submit("Erster", blocker)
    a = q.submit("A", named("A"), {"key": "a", "kind": "index"})
    b = q.submit("B", named("B"), {"key": "b"})
    c = q.submit("C", named("C"), {"key": "c"})
    assert a["position"] == 1 and c["position"] == 3 and not a["duplicate"]
    assert a["entry"]["kind"] == "index" and a["entry"]["queued_at"]
    # Derselbe Auftrag wartet schon: nicht doppelt aufnehmen
    dup = q.submit("A nochmals", named("A2"), {"key": "a"})
    assert dup["duplicate"] and dup["position"] == 1 and len(q) == 3
    assert q.move(c["entry"]["id"], -1)  # C vor B
    assert q.move(a["entry"]["id"], -1)  # schon vorne: bleibt vorne
    assert q.remove(b["entry"]["id"]) and not q.remove(999) and not q.move(999, 1)
    assert [e["title"] for e in q.entries()] == ["A", "C"]
    extra = q.submit("D", named("D"))
    assert extra["position"] == 3 and q.remove(extra["entry"]["id"])
    gate.set()
    assert wait_until(lambda: len(order) == 3 and not jobs.running("index"))
    assert order == ["erster", "A", "C"] and not len(q)


def test_queue_continues_after_error_and_starts_at_once_when_free():
    jobs = JobManager()
    q = JobQueue(jobs, "index", "index")
    gate = threading.Event()

    def failing(job):
        gate.wait(5)
        raise RuntimeError("kaputt")

    first = q.submit("Fehler", failing)["job"]
    done = threading.Event()
    assert q.submit("Danach", lambda job: done.set())["position"] == 1
    gate.set()
    assert done.wait(5) and first.status == "error"
    # Nichts läuft, niemand wartet: sofort starten statt einreihen
    assert wait_until(lambda: not jobs.running("index"))
    assert "job" in q.submit("Gleich", lambda job: None)
    # Beenden mit Abbruch: wartende Aufträge verwerfen, damit nicht gleich der nächste startet
    gate2 = threading.Event()
    assert wait_until(lambda: not jobs.running("index"))
    q.submit("Lang", lambda job: gate2.wait(5))
    started = []
    q.submit("Nie", lambda job: started.append(1))
    assert q.clear() == 1 and not len(q)
    gate2.set()
    assert wait_until(lambda: not jobs.running("index")) and not started


def test_queue_api(zengine, fake_zotero, monkeypatch):
    build_library(fake_zotero)
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    gate = threading.Event()
    calls = []

    def fake_run(self, job, **kw):
        calls.append(kw)
        gate.wait(5)
        return {}

    monkeypatch.setattr(Indexer, "run", fake_run)
    cid = zengine.store.corpora()[0]["id"]
    pid = zengine.ensure_project()
    zengine.store.assign_corpus(pid, cid)
    from zotivity.server.app import create_app

    try:
        with TestClient(create_app(zengine)) as c:
            first = c.post("/api/index/run", json={}, headers=H).json()
            assert first["kind"] == "index" and not first.get("queued")
            q1 = c.post(f"/api/corpora/{cid}/index", json={}, headers=H).json()
            assert q1["queued"] and q1["position"] == 1 and not q1["duplicate"]
            e1 = q1["entry"]
            assert e1["kind"] == "index" and e1["corpus"] == "Alles" and e1["corpus_id"] == cid
            assert e1["projects"] == [zengine.store.project(pid)["name"]]
            q2 = c.post("/api/index/run", json={"embed_only": True}, headers=H).json()
            assert q2["position"] == 2 and q2["entry"]["kind"] == "embed" and q2["entry"]["corpus"] is None
            dup = c.post(f"/api/corpora/{cid}/index", json={}, headers=H).json()
            assert dup["duplicate"] and dup["position"] == 1
            assert [e["kind"] for e in c.get("/api/status").json()["index_queue"]] == ["index", "embed"]
            r = c.post(f"/api/index/queue/{q2['entry']['id']}/move", json={"delta": -1}, headers=H).json()
            assert [e["kind"] for e in r["queue"]] == ["embed", "index"]
            r = c.delete(f"/api/index/queue/{e1['id']}", headers=H).json()
            assert [e["kind"] for e in r["queue"]] == ["embed"]
            assert c.delete("/api/index/queue/999", headers=H).status_code == 404
            assert c.post("/api/index/queue/999/move", json={"delta": 1}, headers=H).status_code == 404
            gate.set()
            assert wait_until(lambda: len(calls) == 2 and not zengine.jobs.running("index"))
            assert calls[1]["embed_only"] is True and c.get("/api/index/queue").json()["queue"] == []
    finally:
        gate.set()


def test_model_switch_during_run_stops_cleanly(zengine, fake_zotero, monkeypatch):
    """Früher bettete der Lauf nach einem Wechsel endlos dieselben Abschnitte in den neuen Raum ein."""
    build_library(fake_zotero)
    old = zengine.space()
    calls = {"n": 0}
    embed_rows = Indexer._embed_rows
    new_emb = NamedHash("hash-neu")

    def spy(self, rows, job, space=None):
        calls["n"] += 1
        if calls["n"] == 2:
            monkeypatch.setattr(zengine, "embedder", lambda: new_emb)  # Wechsel mitten im Lauf
        return embed_rows(self, rows, job, space)

    monkeypatch.setattr(Indexer, "_embed_rows", spy)
    result, job = run_index(zengine)
    assert result["switched"] and result["stopped"] == MODEL_SWITCHED and calls["n"] == 2
    run = zengine.store.index_runs()[0]
    assert run["status"] == "switched" and run["stopped"] == MODEL_SWITCHED
    assert job.counters["space"] == old and zengine.store.busy is None
    new = zengine.space()
    assert new != old and zengine.store.scope_stats(None, new)["embedded"] == 0  # nichts im neuen Raum
    # Der nächste Lauf arbeitet mit dem neuen Modell; schon Gelesenes wird nur eingebettet
    monkeypatch.setattr(Indexer, "_embed_rows", embed_rows)
    result, _ = run_index(zengine)
    assert not result.get("switched") and result["extracted"] <= 1
    st = zengine.store.scope_stats(None, new)
    assert st["indexed"] == 2 and st["embedded"] == st["chunks"]


def test_titlebar_colors():
    assert colorref("#1b1b1c") == 0x1C1B1B
    assert colorref("#FFF") == 0xFFFFFF
    assert colorref(" rgb(1, 2, 3) ") == 0x030201
    assert colorref("rgba(1,2,3,0.5)") == 0x030201
    assert colorref("var(--surface)") is None and colorref(None) is None and colorref("") is None
    assert apply(0, True) is False  # ohne Fenster nichts tun
