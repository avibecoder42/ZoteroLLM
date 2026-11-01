"""Laufzeitdienste: Hintergrund-Indexierung, Startbefehl für das Plugin, Statusdatei."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from zotivity import __version__, paths
from zotivity.engine import Engine
from zotivity.index.indexer import Indexer, in_hour_window, window_end

log = logging.getLogger(__name__)

# Suchkatalog: Versionsvergleich mit Zotero jede Minute, Abgleich nach einer Änderung höchstens alle zwei Minuten
CATALOG_CHECK_SECONDS = 60
CATALOG_MIN_GAP_SECONDS = 120


def launcher_command() -> list[str]:
    """Befehl, mit dem das Zotero-Plugin den Dienst ohne Konsolenfenster starten kann."""
    if getattr(sys, "frozen", False):
        # Installiertes Programm: im Hintergrund starten, das Fenster erscheint bei Bedarf
        return [sys.executable, "--background"]
    exe = Path(sys.executable)
    if os.name == "nt":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
    return [str(exe), "-m", "zotivity", "serve", "--quiet"]


def write_state(host: str, port: int) -> None:
    data = {
        "pid": os.getpid(), "host": host, "port": port, "url": f"http://{host}:{port}/",
        "version": __version__, "started_at": time.time(), "launcher": launcher_command(),
    }
    paths.state_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_state() -> None:
    try:
        data = json.loads(paths.state_file().read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            paths.state_file().unlink()
    except (OSError, ValueError):
        pass


def read_state() -> dict | None:
    try:
        return json.loads(paths.state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class BackgroundScheduler:
    """Startet Indexierläufe automatisch, solange Zotero läuft (Modus „Hintergrund“)."""

    def __init__(self, engine: Engine, on_exit=None, exit_after_minutes: int | None = None):
        self.engine = engine
        self.indexer = Indexer(engine)
        self.on_exit = on_exit
        # Vom Plugin gestartet: Wert aus --exit-with-zotero, sonst aus den Einstellungen
        self.exit_after_minutes = exit_after_minutes
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: float = 0.0
        self.zotero_seen: float = time.time()
        self.zotero_running = False
        # Suchkatalog: Bibliotheken, die Zotero seit dem letzten Abgleich geändert hat (für Hinweis und Abgleich)
        self.catalog_changed: list[str] = []
        self.catalog_checked_at: float = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def trigger_now(self) -> None:
        self.last_run = 0.0

    def trigger_catalog_check(self) -> None:
        """Nach einer Änderung in Zotero durch Zotivity: beim nächsten Takt Versionen vergleichen (statt in bis zu
        einer Minute)."""
        self.catalog_checked_at = 0.0

    def _loop(self) -> None:
        while not self._stop.wait(20):
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                log.exception("Fehler im Hintergrundplaner")

    def _follow_catalog(self, now: float) -> None:
        """Suchkatalog mit Zotero mitführen, sobald er einmal angelegt wurde: jede Minute die Versionsnummern der
        Bibliotheken vergleichen und bei Änderungen abgleichen (nur Geändertes – meist Sekunden), höchstens alle
        zwei Minuten; sonst stündlich. Während einer Indexierung wartet der Abgleich (die Oberfläche zeigt dann
        „Zotero wurde geändert“)."""
        catalog_at = self.engine.store.get_meta("catalog_synced_at")
        if not self.zotero_running or not catalog_at:
            self.catalog_changed = []
            return
        if now - self.catalog_checked_at >= CATALOG_CHECK_SECONDS and not self.engine.jobs.running("catalog"):
            self.catalog_checked_at = now
            try:
                self.catalog_changed = self.indexer.catalog_changes()
            except Exception as e:  # noqa: BLE001 - Zotero kurz nicht erreichbar: beim nächsten Mal
                log.debug("Versionsvergleich mit Zotero nicht möglich: %s", e)
        since = now - float(catalog_at)
        due = (self.catalog_changed and since >= CATALOG_MIN_GAP_SECONDS) or since > 3600
        if due and not self.engine.jobs.running("catalog") and not self.engine.jobs.running("index"):
            try:
                self.engine.jobs.start("catalog", "Suchkatalog abgleichen", lambda job: self.indexer.sync_catalog(job),
                                       group="catalog")
                self.catalog_changed = []
            except RuntimeError:
                pass

    def _tick(self) -> None:
        settings = self.engine.settings
        self.zotero_running = self.engine.zotero().is_available(fresh=True)
        now = time.time()
        if self.zotero_running:
            self.zotero_seen = now
        limit = self.exit_after_minutes or settings.server.exit_after_zotero_closed_minutes
        if limit and now - self.zotero_seen > limit * 60 and self.on_exit:
            if (not self.engine.jobs.running("index") and not len(self.engine.index_queue)
                    and not self.engine.jobs.running("review")):
                # on_exit darf ablehnen (False), z. B. solange das Programmfenster offen ist
                if self.on_exit() is not False:
                    log.info("Zotero seit %d Minuten geschlossen – Dienst beendet", limit)
                    return
        self._follow_catalog(now)
        if settings.indexing.mode != "background" or not self.zotero_running:
            return
        if not self.engine.store.corpora():
            return
        # Läuft eine Indexierung oder warten von Hand gestartete Läufe, hat die automatische Prüfung Pause
        # (die wartenden Läufe erledigen dasselbe)
        if self.engine.jobs.running("index") or len(self.engine.index_queue):
            return
        if now - self.last_run < settings.indexing.interval_minutes * 60:
            return
        icfg = settings.indexing
        current = datetime.now()
        if not in_hour_window(current, icfg.background_from_hour, icfg.background_to_hour):
            return
        self.last_run = now
        deadline = window_end(current, icfg.background_from_hour, icfg.background_to_hour)
        try:
            self.engine.jobs.start(
                "index", "Hintergrund-Indexierung",
                lambda job: self.indexer.run(job, deadline=deadline, max_docs=icfg.background_max_docs,
                                             trigger="background"), group="index")
        except RuntimeError:
            pass

    def next_run_at(self, now: float | None = None) -> float | None:
        """Zeitpunkt der nächsten automatischen Prüfung (None: Hintergrundmodus aus oder kein Korpus)."""
        icfg = self.engine.settings.indexing
        if icfg.mode != "background" or not self.engine.store.corpora():
            return None
        now = now or time.time()
        at = max(now, self.last_run + icfg.interval_minutes * 60)
        if icfg.background_from_hour is not None and icfg.background_to_hour is not None:
            when = datetime.fromtimestamp(at)
            if not in_hour_window(when, icfg.background_from_hour, icfg.background_to_hour):
                start = when.replace(hour=icfg.background_from_hour, minute=0, second=0, microsecond=0)
                if start <= when:
                    start += timedelta(days=1)
                at = start.timestamp()
        return at
