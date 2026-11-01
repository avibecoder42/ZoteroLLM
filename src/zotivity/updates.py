"""Updates wie bei LLMplot: Ein Manifest (JSON) nennt Version, Installer und Prüfsumme.

Quelle ist eine HTTPS-Adresse oder ein lokaler bzw. Netzwerkpfad, z. B.::

    {"version": "0.2.0", "url": "Zotivity-Setup-0.2.0.exe", "sha256": "…", "notes": "…"}

Relative Installer-Angaben gelten relativ zum Manifest. Das Update startet den Installer
unbeaufsichtigt (/SILENT) und beendet Zotivity; der Installer startet das Programm danach neu.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from zotivity import __version__


class UpdateError(ValueError):
    pass


def version_tuple(text: str) -> tuple[int, ...]:
    parts = []
    for p in str(text).split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple((parts + [0] * 4)[:4])


def read_source(source: str, limit: int = 1024 * 1024 * 1024) -> bytes:
    source = source.strip()
    if source.startswith("http://"):
        raise UpdateError("Update-Quellen müssen HTTPS oder ein lokaler bzw. Netzwerkpfad sein.")
    if source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": f"Zotivity/{__version__}"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - nur HTTPS
            return resp.read(limit)
    if source.startswith("file://"):
        source = urllib.request.url2pathname(source[7:])
    path = Path(source)
    if not path.is_file():
        raise UpdateError(f"Update-Quelle nicht gefunden: {source}")
    return path.read_bytes()


def check(source: str) -> dict:
    source = (source or "").strip()
    if not source:
        return {"configured": False, "current": __version__}
    try:
        manifest = json.loads(read_source(source, 1024 * 1024).decode("utf-8-sig"))
    except UpdateError:
        raise
    except (OSError, ValueError) as e:
        raise UpdateError(f"Update-Information konnte nicht gelesen werden: {e}") from e
    latest = str(manifest.get("version", "0"))
    installer = manifest.get("url") or manifest.get("path") or ""
    if installer and not (installer.startswith(("https://", "file://")) or Path(installer).is_absolute()):
        if source.startswith("https://"):
            installer = source.rsplit("/", 1)[0] + "/" + installer
        else:
            installer = str(Path(source.removeprefix("file://")).parent / installer)
    return {"configured": True, "current": __version__, "latest": latest,
            "available": version_tuple(latest) > version_tuple(__version__),
            "installer": installer, "sha256": manifest.get("sha256", ""), "notes": manifest.get("notes", "")}


def download_installer(installer: str, sha256: str = "") -> Path:
    if not installer:
        raise UpdateError("Kein Installer angegeben.")
    data = read_source(installer)
    if sha256 and hashlib.sha256(data).hexdigest().lower() != sha256.lower():
        raise UpdateError("Die Prüfsumme des Installers stimmt nicht. Update abgebrochen.")
    tmp = Path(tempfile.gettempdir()) / f"Zotivity-Setup-{time.strftime('%Y%m%d%H%M%S')}.exe"
    tmp.write_bytes(data)
    return tmp


def run_installer(path: Path) -> bool:
    """Startet den Installer losgelöst. True, wenn Zotivity sich jetzt beenden soll."""
    if sys.platform != "win32":
        return False
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],  # noqa: S603
                     creationflags=flags, close_fds=True)
    return True
