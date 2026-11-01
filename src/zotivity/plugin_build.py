"""Zotero-Plugin als .xpi paketieren (ZIP mit manifest.json im Wurzelverzeichnis).

Hinweis zur update_url: Zotero (Firefox-Basis) deaktiviert Plugins, deren update_url
nicht mit https: beginnt („Updates must be provided over HTTPS“), und verlangt das
Feld zugleich. Der lokale Dienst spricht nur http – daher zeigt die update_url auf
die reservierte Domain .invalid (RFC 2606): Sie löst nie auf, es entsteht kein
Netzwerkverkehr. Aktualisiert wird durch Neuinstallation der .xpi.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from zotivity import __version__

PLUGIN_DIR = Path(__file__).parent / "plugin"
PLUGIN_ID = "zotivity@zotivity.local"


def xpi_bytes(service_url: str = "http://127.0.0.1:23120/") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(PLUGIN_DIR.rglob("*")):
            if path.is_dir() or path.name.startswith(".") or path.suffix == ".pyc":
                continue
            rel = path.relative_to(PLUGIN_DIR).as_posix()
            data = path.read_bytes()
            if rel == "manifest.json":
                manifest = json.loads(data)
                manifest["version"] = __version__
                data = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
            elif rel == "prefs.js":
                data = data.replace(b"http://127.0.0.1:23120/", service_url.encode())
            z.writestr(rel, data)
    return buf.getvalue()


def build_xpi(out_dir: Path | None = None, service_url: str | None = None) -> Path:
    from zotivity.settings import SettingsStore

    if service_url is None:
        s = SettingsStore().get().server
        service_url = f"http://{s.host}:{s.port}/"
    out_dir = out_dir or Path.cwd() / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"zotivity-{__version__}.xpi"
    path.write_bytes(xpi_bytes(service_url))
    return path
