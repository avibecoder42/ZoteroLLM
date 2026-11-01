"""Textextraktion in einem eigenen Prozess mit Zeitlimit.

Eine defekte PDF kann die PDF-Bibliothek hart abstürzen lassen (ohne Python-Fehler) oder endlos hängen.
Läuft das Lesen in einem eigenen Prozess, trifft das nur diesen einen Text: Er wird als Fehler markiert,
der Prozess wird neu gestartet und die Indexierung geht mit dem nächsten Text weiter.
"""

from __future__ import annotations

import importlib
import logging
import multiprocessing as mp
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

DEFAULT_TARGET = "zotivity.extract.pdf:extract_file"


class ExtractionFailed(RuntimeError):
    """Der Lese-Prozess ist abgestürzt oder hat das Zeitlimit überschritten."""


def _resolve(target: str) -> Callable:
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


def _serve(conn, target: str) -> None:  # läuft im Kindprozess
    func = _resolve(target)
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        args, kwargs = msg
        try:
            conn.send(("ok", func(*args, **kwargs)))
        except Exception as e:  # noqa: BLE001 - Fehler gehen als Meldung zurück
            conn.send(("err", f"{type(e).__name__}: {e}"))


class ExtractionWorker:
    """Ein wiederverwendeter Kindprozess; wird nach Absturz oder Zeitüberschreitung neu gestartet."""

    def __init__(self, target: str = DEFAULT_TARGET):
        self.target = target
        self._proc = None
        self._conn = None
        self._lock = threading.Lock()
        self.starts = 0

    @property
    def restarts(self) -> int:
        """Neustarts nach Absturz oder Zeitüberschreitung."""
        return max(0, self.starts - 1)

    def _start(self) -> None:
        self.starts += 1
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._proc = ctx.Process(target=_serve, args=(child, self.target), name="zotivity-extract", daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent

    def call(self, *args, timeout: float, check: Callable[[], None] | None = None, **kwargs):
        """Ruft die Zielfunktion im Kindprozess auf. check() wird regelmässig aufgerufen (Abbruch)."""
        with self._lock:
            if self._proc is None or not self._proc.is_alive():
                self._start()
            try:
                self._conn.send((args, kwargs))
            except (BrokenPipeError, OSError) as e:
                self._kill()
                raise ExtractionFailed("Lese-Prozess nicht erreichbar") from e
            deadline = time.monotonic() + timeout
            while True:
                try:
                    ready = self._conn.poll(0.25)
                except (BrokenPipeError, EOFError, OSError):
                    ready = True
                if ready:
                    break
                if not self._proc.is_alive():
                    code = self._proc.exitcode
                    self._kill()
                    raise ExtractionFailed(f"Datei hat das Lesen zum Absturz gebracht (Code {code})")
                if time.monotonic() > deadline:
                    self._kill()
                    raise ExtractionFailed(f"Lesen nach {int(timeout)} s abgebrochen (Zeitlimit)")
                if check is not None:
                    try:
                        check()
                    except BaseException:
                        self._kill()
                        raise
            try:
                status, value = self._conn.recv()
            except (EOFError, OSError) as e:
                code = self._proc.exitcode if self._proc else None
                self._kill()
                raise ExtractionFailed(f"Datei hat das Lesen zum Absturz gebracht (Code {code})") from e
            if status == "err":
                raise RuntimeError(value)
            return value

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if proc is not None and proc.is_alive():
            proc.kill()
            proc.join(5)

    def stop(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.send(None)
                except OSError:
                    pass
            if self._proc is not None:
                self._proc.join(2)
            self._kill()
