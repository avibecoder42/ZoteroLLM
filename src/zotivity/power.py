"""Ruhezustand verhindern, solange eine lange Indexierung läuft (Bildschirm darf trotzdem ausgehen)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from contextlib import contextmanager

log = logging.getLogger(__name__)


@contextmanager
def keep_awake(enabled: bool = True):
    if not enabled:
        yield
        return
    if sys.platform == "win32":
        import ctypes

        es_continuous, es_system_required = 0x80000000, 0x00000001
        # Gilt für den aufrufenden Thread – der Indexierauftrag läuft in seinem eigenen Thread
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)
        try:
            yield
        finally:
            ctypes.windll.kernel32.SetThreadExecutionState(es_continuous)
        return
    proc = None
    try:
        if sys.platform == "darwin":
            proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])  # noqa: S603, S607
        else:
            proc = subprocess.Popen(["systemd-inhibit", "--what=idle:sleep", "--why=Zotivity indexiert",  # noqa: S603, S607
                                     "sleep", "infinity"])
    except OSError as e:
        log.info("Ruhezustand kann nicht verhindert werden: %s", e)
    try:
        yield
    finally:
        if proc is not None:
            proc.terminate()
