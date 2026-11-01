"""Plattformabhängige Speicherorte.

Windows: %LOCALAPPDATA%\\Zotivity          (Index, Logs)
         %APPDATA%\\Zotivity               (Einstellungen)
macOS:   ~/Library/Application Support/Zotivity
Linux:   ~/.local/share/Zotivity, ~/.config/Zotivity

Der Index liegt bewusst NICHT im Zotero-Datenordner: dieser wird oft über
Cloud-Ordner synchronisiert (z. B. switchdrive), was bei grossen SQLite-Dateien
zu Konflikten führt. Mit ZOTIVITY_HOME lässt sich alles in einen Ordner legen.

Bis Version 1.0.1 hiess das Programm ZotLLM, bis 0.7.3 ZoteroLLM: Deren Ordner werden beim ersten Start umbenannt. Gelingt das
nicht (z. B. weil die alte Version noch läuft), bleiben die alten Ordner in Gebrauch – nie ein leerer Neuanfang.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from platformdirs import PlatformDirs

from zotivity import APP_NAME, LEGACY_NAMES

log = logging.getLogger(__name__)


def _platform_dirs(name: str) -> PlatformDirs:
    return PlatformDirs(appname=name, appauthor=False, roaming=False)


def _adopt_legacy(new: PlatformDirs, old: PlatformDirs) -> bool:
    """Ordner des früheren Namens übernehmen – alle oder keinen. False: die alten Ordner bleiben in Gebrauch."""
    moved: list[tuple[Path, Path]] = []
    # Daten zuerst: unter Windows liegen Einstellungen und Logs darin und ziehen mit um
    for attr in ("user_data_dir", "user_config_dir", "user_log_dir"):
        src, dst = Path(getattr(old, attr)), Path(getattr(new, attr))
        if not src.is_dir() or dst.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            moved.append((src, dst))
        except OSError as e:  # z. B. Dateien der alten Version noch geöffnet
            log.warning("Ordner %s nicht umbenannt: %s", src, e)
            for back_src, back_dst in reversed(moved):
                os.replace(back_dst, back_src)
            return False
    for src, dst in moved:
        log.info("Ordner übernommen: %s → %s", src, dst)
    return True


@lru_cache(maxsize=1)
def _dirs() -> PlatformDirs:
    new = _platform_dirs(APP_NAME)
    if Path(new.user_data_dir).is_dir():
        return new
    for name in LEGACY_NAMES:
        old = _platform_dirs(name)
        if Path(old.user_data_dir).is_dir():
            return new if _adopt_legacy(new, old) else old
    return new


def _override() -> Path | None:
    home = os.environ.get("ZOTIVITY_HOME") or os.environ.get("ZOTLLM_HOME") or os.environ.get("ZOTEROLLM_HOME")  # frühere Namen
    return Path(home).expanduser() if home else None


def data_dir() -> Path:
    base = _override() or Path(_dirs().user_data_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_dir() -> Path:
    base = (_override() / "config") if _override() else Path(_dirs().user_config_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_dir() -> Path:
    base = (_override() / "logs") if _override() else Path(_dirs().user_log_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_file() -> Path:
    return config_dir() / "settings.json"


def index_db_file() -> Path:
    return data_dir() / "index.sqlite3"


def state_file() -> Path:
    """Laufzeitinformationen (Port, PID) für Plugin und CLI."""
    return data_dir() / "service.json"


def models_dir() -> Path:
    """Heruntergeladene Embedding-Modelle (GGUF) – lokal, nie in einem Cloud-Ordner."""
    base = data_dir() / "models"
    base.mkdir(parents=True, exist_ok=True)
    return base
