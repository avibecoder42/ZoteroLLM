"""Zielfunktionen für den Lese-Prozess in Tests (laufen im Kindprozess)."""

import os
import time


def flaky_extract(path, content_type, **kwargs):
    """Simuliert defekte Dateien: „CRASH“ im Pfad beendet den Prozess hart, „HANG“ hängt."""
    name = os.path.basename(str(path)).upper()
    if "CRASH" in name:
        os._exit(3)
    if "HANG" in name:
        time.sleep(120)
    from zotivity.extract.pdf import extract_file

    return extract_file(path, content_type, **kwargs)
