"""Holt die eingebaute Embedding-Laufzeit (llama.cpp) für den Build nach build/vendor/llama.

Version, Download-Adresse und SHA-256 stehen in packaging/llama_cpp.json. Das Archiv wird in build/vendor
zwischengespeichert (kein erneuter Download), geprüft und nur mit den für llama-server nötigen Dateien entpackt.

Aufruf: python packaging/fetch_llama.py
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "packaging" / "llama_cpp.json").read_text(encoding="utf-8"))
VENDOR = ROOT / "build" / "vendor"
TARGET = VENDOR / "llama"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"Lade {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Zotivity-build"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as fh:  # noqa: S310 - feste HTTPS-Adresse
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Nur das Windows-Paket ist eingetragen (packaging/llama_cpp.json).")
    spec = CONFIG["windows-x64"]
    VENDOR.mkdir(parents=True, exist_ok=True)
    archive = VENDOR / spec["asset"]
    stamp = TARGET / "BUILD.txt"
    if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == CONFIG["build"]:
        print(f"llama.cpp {CONFIG['build']} ist bereits vorhanden: {TARGET}")
        return
    if not archive.exists() or sha256(archive) != spec["sha256"]:
        download(spec["url"], archive)
    if sha256(archive) != spec["sha256"]:
        archive.unlink()
        raise SystemExit("Prüfsumme des llama.cpp-Archivs stimmt nicht – abgebrochen.")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if info.is_dir() or not any(fnmatch.fnmatch(name, p) for p in CONFIG["files"]):
                continue
            with z.open(info) as src, open(TARGET / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
    license_file = VENDOR / f"LICENSE-llama.cpp-{CONFIG['build']}"
    if not license_file.exists():
        download(CONFIG["license_url"], license_file)
    shutil.copy2(license_file, TARGET / "LICENSE-llama.cpp")
    stamp.write_text(CONFIG["build"], encoding="utf-8")
    total = sum(p.stat().st_size for p in TARGET.iterdir())
    print(f"llama.cpp {CONFIG['build']}: {len(list(TARGET.iterdir()))} Dateien, {total / 1e6:.1f} MB in {TARGET}")


if __name__ == "__main__":
    main()
