"""Hintergrundaufträge mit Fortschritt, Abbruch und Ereignisprotokoll."""

from __future__ import annotations

import itertools
import logging
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from typing import Any

from zotivity.i18n import tr, tr_exact, tr_fields
from zotivity.llm.base import UsageMeter

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class Job:
    _ids = itertools.count(1)

    def __init__(self, kind: str, title: str):
        self.id = next(self._ids)
        self.kind = kind
        self.title = title
        self.status = "queued"  # queued, running, done, error, cancelled
        self.phase = ""
        self.done = 0
        self.total = 0
        self.message = ""
        self.error: str | None = None
        self.result: Any = None
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.meter = UsageMeter()
        self.counters: dict[str, Any] = {}
        self.log: deque[str] = deque(maxlen=200)
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def update(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def step(self, n: int = 1, message: str | None = None) -> None:
        with self._lock:
            self.done += n
            if message is not None:
                self.message = message

    def note(self, line: str) -> None:
        self.log.append(time.strftime("%H:%M:%S ") + line)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    def sleep(self, seconds: float) -> None:
        if self._cancel.wait(seconds):
            raise JobCancelled()

    def as_dict(self) -> dict:
        with self._lock:
            elapsed = (self.finished_at or time.time()) - self.started_at
            eta = None
            if self.status == "running" and self.total and self.done:
                eta = elapsed / self.done * (self.total - self.done)
            counters = dict(self.counters)
            # Meldungen in der Sprache der Oberfläche (Quelltext und Protokoll bleiben deutsch)
            if isinstance(counters.get("current"), dict):
                cur = tr_fields(counters["current"], "step")
                cur["title"] = tr_exact(cur.get("title"))  # sonst der Titel des Texts
                counters["current"] = cur
            if isinstance(counters.get("recent"), list):
                counters["recent"] = [tr_fields(r, "message") if isinstance(r, dict) else r for r in counters["recent"]]
            if isinstance(counters.get("stopped"), str):
                counters["stopped"] = tr(counters["stopped"])
            return {
                "id": self.id, "kind": self.kind, "title": tr(self.title), "status": self.status,
                "phase": tr(self.phase), "done": self.done, "total": self.total, "message": tr(self.message),
                "error": tr(self.error), "started_at": self.started_at, "finished_at": self.finished_at,
                "elapsed": elapsed, "eta": eta, "usage": self.meter.usage.as_dict(), "log": list(self.log)[-30:],
                "counters": counters,
            }


class JobManager:
    def __init__(self):
        self._jobs: dict[int, Job] = {}
        self._group_running: dict[str, int] = {}
        self._listeners: dict[str, list[Callable[[Job], Any]]] = {}
        self._lock = threading.Lock()

    def on_finished(self, group: str, fn: Callable[[Job], Any]) -> None:
        """fn(job) nach dem Ende jedes Auftrags der Gruppe aufrufen (im Thread des Auftrags, Status schon gesetzt)."""
        self._listeners.setdefault(group, []).append(fn)

    def start(self, kind: str, title: str, fn: Callable[[Job], Any], group: str | None = None) -> Job:
        """Startet fn(job) im Hintergrund. Pro Gruppe läuft höchstens ein Auftrag."""
        with self._lock:
            if group and group in self._group_running:
                running = self._jobs.get(self._group_running[group])
                if running and running.status in ("queued", "running"):
                    raise RuntimeError(f"Es läuft bereits ein Auftrag: {running.title}")
            job = Job(kind, title)
            self._jobs[job.id] = job
            if group:
                self._group_running[group] = job.id
            self._prune()

        def runner():
            job.update(status="running")
            try:
                job.result = fn(job)
                job.update(status="cancelled" if job.cancelled else "done")
            except JobCancelled:
                job.update(status="cancelled", message="Abgebrochen")
            except Exception as e:  # noqa: BLE001
                log.error("Auftrag %s fehlgeschlagen: %s", job.title, traceback.format_exc())
                job.update(status="error", error=str(e) or type(e).__name__)
            finally:
                job.update(finished_at=time.time())
                for listener in self._listeners.get(group, []) if group else []:
                    try:
                        listener(job)
                    except Exception:  # noqa: BLE001
                        log.exception("Nachfolger von Auftrag %s fehlgeschlagen", job.title)

        threading.Thread(target=runner, name=f"job-{job.id}-{kind}", daemon=True).start()
        return job

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def running(self, group: str) -> Job | None:
        job_id = self._group_running.get(group)
        job = self._jobs.get(job_id) if job_id else None
        return job if job and job.status in ("queued", "running") else None

    def list(self) -> list[dict]:
        return [j.as_dict() for j in sorted(self._jobs.values(), key=lambda j: -j.id)]

    def cancel(self, job_id: int) -> bool:
        job = self._jobs.get(job_id)
        if job and job.status in ("queued", "running"):
            job.cancel()
            return True
        return False

    def _prune(self) -> None:
        finished = [j for j in self._jobs.values() if j.status in ("done", "error", "cancelled")]
        for j in sorted(finished, key=lambda j: j.id)[:-30]:
            self._jobs.pop(j.id, None)


class JobQueue:
    """Warteschlange einer Auftragsgruppe (Indexierung): Läuft schon ein Auftrag, wartet ein neuer, bis er an der
    Reihe ist – statt abgelehnt zu werden. Die Reihenfolge lässt sich ändern, Einträge lassen sich entfernen.
    Die Warteschlange lebt im Speicher: Beim Beenden des Programms verfällt sie (der Index selbst bleibt)."""

    def __init__(self, jobs: JobManager, kind: str, group: str):
        self.jobs, self.kind, self.group = jobs, kind, group
        self._entries: list[dict] = []
        self._fns: dict[int, Callable[[Job], Any]] = {}
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        jobs.on_finished(group, lambda _job: self.advance())

    def submit(self, title: str, fn: Callable[[Job], Any], info: dict | None = None) -> dict:
        """Sofort starten, wenn nichts läuft und niemand wartet; sonst hinten anstellen.
        Antwort: {"job": Job} oder {"entry": …, "position": n, "duplicate": bool}. Ein gleicher Auftrag
        (gleicher "key" in info), der schon wartet, wird nicht ein zweites Mal aufgenommen."""
        info = dict(info or {})
        with self._lock:
            if not self._entries:
                try:
                    return {"job": self.jobs.start(self.kind, title, fn, group=self.group)}
                except RuntimeError:
                    pass  # es läuft schon ein Auftrag: anstellen
            key = info.get("key")
            for pos, e in enumerate(self._entries, 1):
                if key and e.get("key") == key:
                    return {"entry": dict(e), "position": pos, "duplicate": True}
            entry = {**info, "id": next(self._ids), "title": title, "queued_at": time.time()}
            self._entries.append(entry)
            self._fns[entry["id"]] = fn
            position = len(self._entries)
        self.advance()  # falls der laufende Auftrag eben geendet hat
        return {"entry": dict(entry), "position": position, "duplicate": False}

    def advance(self) -> Job | None:
        """Den nächsten wartenden Auftrag starten, sobald die Gruppe frei ist."""
        with self._lock:
            if not self._entries or self.jobs.running(self.group):
                return None
            entry = self._entries.pop(0)
            fn = self._fns.pop(entry["id"])
            try:
                return self.jobs.start(self.kind, entry["title"], fn, group=self.group)
            except RuntimeError:  # ein anderer Auftrag kam dazwischen: vorne wieder einreihen
                self._entries.insert(0, entry)
                self._fns[entry["id"]] = fn
                return None

    def entries(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

    def move(self, entry_id: int, delta: int) -> bool:
        """Eintrag um delta Plätze verschieben (−1: früher, +1: später)."""
        with self._lock:
            i = next((n for n, e in enumerate(self._entries) if e["id"] == entry_id), None)
            if i is None:
                return False
            j = max(0, min(len(self._entries) - 1, i + delta))
            self._entries.insert(j, self._entries.pop(i))
            return True

    def remove(self, entry_id: int) -> bool:
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e["id"] != entry_id]
            self._fns.pop(entry_id, None)
            return len(self._entries) < before

    def clear(self) -> int:
        """Alle wartenden Aufträge verwerfen (z. B. beim Beenden mit Abbruch); Anzahl der verworfenen."""
        with self._lock:
            n = len(self._entries)
            self._entries, self._fns = [], {}
            return n
