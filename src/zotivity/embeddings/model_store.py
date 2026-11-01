"""Heruntergeladene Embedding-Modelle: Download (fortsetzbar, mit Prüfsumme), Verzeichnis, Löschen.

Die Dateien liegen im lokalen Datenordner (``paths.models_dir()``), nie in einem Cloud-Ordner.
``installed.json`` hält fest, welche Datei zu welchem Modell gehört, und die Ergebnisse des Kurztests.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

import httpx

from zotivity import __version__, paths
from zotivity.embeddings.base import EmbeddingError
from zotivity.embeddings.gguf import GGUFError, inspect
from zotivity.embeddings.model_catalog import ModelEntry

CHUNK = 1 << 20
_lock = threading.RLock()


def registry_file() -> Path:
    return paths.models_dir() / "installed.json"


def _read() -> dict:
    path = registry_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    path = registry_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def model_dir(model_id: str) -> Path:
    return paths.models_dir() / model_id


def installed() -> dict[str, dict]:
    """Nur Einträge, deren Datei noch vorhanden ist."""
    with _lock:
        out = {}
        for mid, rec in _read().items():
            p = paths.models_dir() / rec.get("path", "")
            if rec.get("path") and p.is_file():
                out[mid] = {**rec, "abs_path": str(p)}
        return out


def record(model_id: str) -> dict | None:
    return installed().get(model_id)


def model_path(model_id: str) -> Path | None:
    rec = record(model_id)
    return Path(rec["abs_path"]) if rec else None


def part_file(entry: ModelEntry) -> Path:
    return model_dir(entry.id) / (entry.file.name + ".part")


def partial_bytes(entry: ModelEntry) -> int:
    p = part_file(entry)
    return p.stat().st_size if p.exists() else 0


def _http() -> httpx.Client:
    # trust_env: Proxy-Einstellungen des Systems gelten (Downloads aus dem Internet)
    return httpx.Client(follow_redirects=True, trust_env=True, headers={"User-Agent": f"Zotivity/{__version__}"},
                        timeout=httpx.Timeout(60.0, connect=15.0))


def download(entry: ModelEntry, job=None, http: httpx.Client | None = None) -> dict:
    """Lädt die Modelldatei herunter. Ein abgebrochener Download wird beim nächsten Mal fortgesetzt."""
    target_dir = model_dir(entry.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / entry.file.name
    part = part_file(entry)
    size, sha = entry.file.bytes, entry.file.sha256
    free = shutil.disk_usage(target_dir).free
    need = size - partial_bytes(entry) + 200 * 1024 * 1024
    if free < need:
        raise EmbeddingError(f"Zu wenig Speicherplatz: frei {free / 2**30:.1f} GB, benötigt {need / 2**30:.1f} GB.")
    h = hashlib.sha256()
    done = 0
    if part.exists():
        with open(part, "rb") as fh:  # bisherigen Teil in die Prüfsumme aufnehmen
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
                done += len(chunk)
        if done > size:
            part.unlink()
            h, done = hashlib.sha256(), 0
    if job:
        job.update(phase="Download", total=size, done=done,
                   message="Download wird fortgesetzt …" if done else "Download startet …")
    client = http or _http()
    try:
        if done < size:
            headers = {"Range": f"bytes={done}-"} if done else {}
            with client.stream("GET", entry.download_url, headers=headers) as r:
                if r.status_code == 416 or r.status_code >= 400:
                    raise EmbeddingError(f"Download fehlgeschlagen (HTTP {r.status_code}).",
                                         transient=r.status_code >= 500)
                if done and r.status_code != 206:  # Server setzt nicht fort: von vorn
                    h, done = hashlib.sha256(), 0
                mode = "ab" if done else "wb"
                last = time.time()
                with open(part, mode) as fh:
                    for chunk in r.iter_bytes(CHUNK):
                        if job:
                            job.check()
                        fh.write(chunk)
                        h.update(chunk)
                        done += len(chunk)
                        if job and time.time() - last > 0.3:
                            job.update(done=done, message="Download läuft …")
                            last = time.time()
    except httpx.TransportError as e:
        raise EmbeddingError(f"Download unterbrochen ({e.__class__.__name__}). Erneut starten setzt ihn fort.",
                             transient=True) from e
    finally:
        if http is None:
            client.close()
    if job:
        job.update(done=done, message="Prüfsumme wird kontrolliert …")
    if done != size or h.hexdigest() != sha:
        part.unlink(missing_ok=True)
        raise EmbeddingError("Die heruntergeladene Datei stimmt nicht mit der Prüfsumme überein und wurde verworfen.")
    try:
        meta = inspect(part)
    except GGUFError as e:
        part.unlink(missing_ok=True)
        raise EmbeddingError(f"Die Datei ist kein gültiges GGUF-Modell: {e}") from e
    os.replace(part, final)
    rec = {"file": entry.file.name, "path": f"{entry.id}/{entry.file.name}", "repo": entry.source.repo,
           "revision": entry.source.revision, "sha256": sha, "bytes": size, "downloaded_at": time.time(),
           "gguf": meta}
    with _lock:
        data = _read()
        old = data.get(entry.id)
        if old and old.get("path") != rec["path"]:  # andere Datei desselben Modells ersetzt
            (paths.models_dir() / old["path"]).unlink(missing_ok=True)
        data[entry.id] = rec
        _write(data)
    return rec


def discard_partial(entry: ModelEntry) -> None:
    part_file(entry).unlink(missing_ok=True)


def delete(model_id: str) -> bool:
    with _lock:
        data = _read()
        rec = data.pop(model_id, None)
        folder = model_dir(model_id)
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
        _write(data)
        return rec is not None


def set_test(model_id: str, result: dict) -> None:
    with _lock:
        data = _read()
        if model_id in data:
            data[model_id]["test"] = result
            _write(data)


def used_bytes() -> int:
    total = 0
    for p in paths.models_dir().rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total
