"""Kopfdaten von GGUF-Dateien lesen (Architektur, Dimension, Kontextlänge, Pooling).

Liest nur den Metadaten-Block am Dateianfang; grosse Listen (Wortschatz) werden übersprungen.
Format: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

POOLING = {0: "none", 1: "mean", 2: "cls", 3: "last", 4: "rank"}

_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9


class GGUFError(ValueError):
    pass


def _read(fh: BinaryIO, fmt: str):
    size = struct.calcsize(fmt)
    data = fh.read(size)
    if len(data) != size:
        raise GGUFError("GGUF-Datei ist unvollständig.")
    return struct.unpack(fmt, data)[0]


def _string(fh: BinaryIO) -> str:
    n = _read(fh, "<Q")
    if n > 1 << 24:
        raise GGUFError("GGUF-Datei ist beschädigt (Zeichenkette zu lang).")
    return fh.read(n).decode("utf-8", errors="replace")


def _value(fh: BinaryIO, typ: int, keep: bool):
    if typ in _SCALAR:
        return _read(fh, _SCALAR[typ])
    if typ == _STRING:
        return _string(fh)
    if typ == _ARRAY:
        item, n = _read(fh, "<I"), _read(fh, "<Q")
        if item in _SCALAR:
            size = struct.calcsize(_SCALAR[item])
            if keep and n <= 64:
                return [_read(fh, _SCALAR[item]) for _ in range(n)]
            fh.seek(size * n, 1)
            return None
        if item == _STRING:
            if keep and n <= 64:
                return [_string(fh) for _ in range(n)]
            for _ in range(n):  # Wortschatz: nur die Längen lesen und überspringen
                fh.seek(_read(fh, "<Q"), 1)
            return None
        raise GGUFError(f"Unbekannter Listentyp {item} in der GGUF-Datei.")
    raise GGUFError(f"Unbekannter Werttyp {typ} in der GGUF-Datei.")


def read_metadata(path: str | Path, max_keys: int = 4096) -> dict:
    """Alle Metadaten ausser grossen Listen. Wirft GGUFError, wenn es keine GGUF-Datei ist."""
    with open(path, "rb") as fh:
        if fh.read(4) != b"GGUF":
            raise GGUFError("Keine GGUF-Datei.")
        version = _read(fh, "<I")
        if version < 2:
            raise GGUFError(f"GGUF-Version {version} wird nicht unterstützt.")
        _read(fh, "<Q")  # Anzahl Tensoren
        n_kv = _read(fh, "<Q")
        meta: dict = {"gguf.version": version}
        for _ in range(min(n_kv, max_keys)):
            key = _string(fh)
            typ = _read(fh, "<I")
            meta[key] = _value(fh, typ, keep=not key.startswith("tokenizer."))
        return meta


def summarize(meta: dict) -> dict:
    """Das Wichtigste für Embeddings: Architektur, Dimension, Kontext, Pooling, kausal."""
    arch = str(meta.get("general.architecture") or "")
    pooling = meta.get(f"{arch}.pooling_type")
    return {
        "architecture": arch,
        "name": meta.get("general.name") or "",
        # EmbeddingGemma 2: Ausgabe (768) grösser als die interne Breite (512)
        "dim": meta.get(f"{arch}.embedding_length_out") or meta.get(f"{arch}.embedding_length"),
        "context": meta.get(f"{arch}.context_length"),
        "pooling": POOLING.get(pooling, "") if pooling is not None else "",
        "causal": meta.get(f"{arch}.attention.causal"),
        "file_type": meta.get("general.file_type"),
    }


def inspect(path: str | Path) -> dict:
    return summarize(read_metadata(path))
