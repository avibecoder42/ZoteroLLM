"""Grosse Bibliotheken: defekte Dateien, Ausfälle des Embedding-Dienstes, Umzug, Etappen, Sicherung."""

import os
import time
from datetime import datetime
from pathlib import Path

import pytest
from test_indexing_search import build_library, run_index

from zotivity.embeddings import EmbeddingError
from zotivity.extract.worker import ExtractionFailed, ExtractionWorker
from zotivity.index.indexer import Indexer, in_hour_window, window_end
from zotivity.jobs import Job

TEXT = ("Digitale Partizipation in der Sozialen Arbeit wird in diesem Abschnitt ausführlich diskutiert. " * 20)


def test_worker_survives_crash_and_hang(tmp_path):
    from fakes import make_pdf

    ok = make_pdf(tmp_path / "ok.pdf", [TEXT])
    worker = ExtractionWorker("worker_targets:flaky_extract")
    try:
        with pytest.raises(ExtractionFailed, match="Absturz"):
            worker.call(tmp_path / "CRASH.pdf", "application/pdf", timeout=30)
        with pytest.raises(ExtractionFailed, match="Zeitlimit"):
            worker.call(tmp_path / "HANG.pdf", "application/pdf", timeout=3)
        doc = worker.call(ok, "application/pdf", timeout=30)
        assert "Partizipation" in doc.pages[0].text
        assert worker.restarts == 2
    finally:
        worker.stop()


def test_defective_pdfs_do_not_stop_the_run(zengine, fake_zotero):
    zengine.settings_store.update({"indexing": {"isolate_extraction": True, "extract_timeout_seconds": 10}})
    fake_zotero.add_item("ITEMA001", "Kaputt", "A", "2020")
    fake_zotero.add_pdf("ATTCRASH", "ITEMA001", [TEXT])
    fake_zotero.add_item("ITEMB001", "Hängt", "B", "2021")
    fake_zotero.add_pdf("ATTHANG1", "ITEMB001", [TEXT])
    fake_zotero.add_item("ITEMC001", "Gut", "C", "2022")
    fake_zotero.add_pdf("ATTOK001", "ITEMC001", [TEXT])
    indexer = Indexer(zengine)
    indexer.worker_target = "worker_targets:flaky_extract"
    result = indexer.run(Job("index", "t"))
    assert result["extracted"] == 1 and result["errors"] == 2
    st = {k: zengine.store.attachment("users/0", k) for k in ("ATTCRASH", "ATTHANG1", "ATTOK001")}
    assert st["ATTCRASH"]["status"] == "error" and "Absturz" in st["ATTCRASH"]["error"]
    assert st["ATTHANG1"]["status"] == "error" and "Zeitlimit" in st["ATTHANG1"]["error"]
    assert st["ATTOK001"]["status"] == "indexed"


def test_embedding_outage_is_bridged(zengine, fake_zotero, monkeypatch):
    build_library(fake_zotero)
    emb = zengine.embedder()
    real = emb.embed_documents
    calls = {"n": 0}

    def flaky(texts):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise EmbeddingError("Ollama ist nicht erreichbar. Läuft Ollama?", transient=True)
        return real(texts)

    monkeypatch.setattr(emb, "embed_documents", flaky)
    monkeypatch.setattr(Job, "sleep", lambda self, s: None)
    result, job = run_index(zengine)
    assert result["embedded"] > 0 and any("wieder erreichbar" in line for line in job.log)


def test_permanent_embedding_error_stops_immediately(zengine, fake_zotero, monkeypatch):
    build_library(fake_zotero)
    emb = zengine.embedder()

    def broken(texts):
        raise EmbeddingError("Modell fehlt")

    monkeypatch.setattr(emb, "embed_documents", broken)
    slept = []
    monkeypatch.setattr(Job, "sleep", lambda self, s: slept.append(s))
    with pytest.raises(EmbeddingError):
        run_index(zengine)
    assert slept == []


def test_moved_files_with_new_timestamps_are_not_reindexed(zengine, fake_zotero):
    build_library(fake_zotero)
    run_index(zengine)
    att = zengine.store.attachment("users/0", "ATTB0001")
    path = Path(att["path"])
    later = time.time() + 5000
    os.utime(path, (later, later))  # z. B. Datenordner kopiert: gleicher Inhalt, neue Änderungszeit
    result, _ = run_index(zengine)
    att2 = zengine.store.attachment("users/0", "ATTB0001")
    assert result["extracted"] == 0 and att2["status"] == "indexed"
    assert abs(att2["file_mtime"] - later) < 2
    # Inhalt wirklich geändert → neu indexieren
    path.write_bytes(path.read_bytes() + b"\n% geaendert\n")
    os.utime(path, (later + 100, later + 100))
    result, _ = run_index(zengine)
    assert result["extracted"] == 1


def test_hour_window():
    at = lambda h: datetime(2026, 10, 11, h, 30)  # noqa: E731
    assert in_hour_window(at(23), 22, 7) and in_hour_window(at(3), 22, 7) and not in_hour_window(at(12), 22, 7)
    assert in_hour_window(at(10), 9, 17) and not in_hour_window(at(18), 9, 17)
    assert in_hour_window(at(12), None, None)
    end = datetime.fromtimestamp(window_end(at(23), 22, 7))
    assert (end.day, end.hour) == (12, 7)


def test_stage_limit_and_deadline(zengine, fake_zotero):
    build_library(fake_zotero)
    result, job = run_index(zengine, max_docs=1)
    assert result["extracted"] == 1 and "Etappe" in result["stopped"]
    result, _ = run_index(zengine)  # nächster Lauf macht weiter
    assert result["extracted"] == 1
    fake_zotero.add_item("ITEMD001", "Neu", "D", "2023")
    fake_zotero.add_pdf("ATTD0001", "ITEMD001", [TEXT])
    result, _ = run_index(zengine, deadline=time.time() - 1)
    assert result["extracted"] == 0 and "Zeitfenster" in result["stopped"]


def test_disk_space_is_checked(zengine, fake_zotero, monkeypatch):
    build_library(fake_zotero)
    monkeypatch.setattr("zotivity.index.indexer.shutil.disk_usage",
                        lambda p: type("U", (), {"free": 50 * 1024 * 1024})())
    with pytest.raises(RuntimeError, match="Speicherplatz"):
        run_index(zengine)


def test_backup_after_run_keeps_two(zengine, fake_zotero, monkeypatch):
    zengine.settings_store.update({"indexing": {"backup_after_run": True}})
    build_library(fake_zotero)
    run_index(zengine)
    indexer = Indexer(zengine)
    files = sorted(indexer.backup_dir().glob("index-*.sqlite3"))
    assert len(files) == 1 and files[0].stat().st_size > 0
    assert indexer.maybe_backup() is None  # höchstens alle 12 Stunden
    for _ in range(3):
        time.sleep(1.1)  # Dateinamen enthalten Sekunden
        indexer.maybe_backup(force=True)
    assert len(list(indexer.backup_dir().glob("index-*.sqlite3"))) == 2
