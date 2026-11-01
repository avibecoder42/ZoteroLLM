"""Programmsymbol aus dem SVG der Oberfläche erzeugen: zotivity.ico (Windows) und icon.png (Linux, 256 px).

Aufruf: python packaging/make_icons.py   (benötigt nur PyMuPDF, das Zotivity ohnehin verwendet)
"""

from __future__ import annotations

import struct
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "src" / "zotivity" / "server" / "static" / "img" / "icon.svg"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(size: int) -> bytes:
    doc = fitz.open(stream=SVG.read_bytes(), filetype="svg")
    page = doc[0]
    scale = size / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
    return pix.tobytes("png")


def write_ico(path: Path, pngs: dict[int, bytes]) -> None:
    """ICO mit eingebetteten PNG-Bildern (ab Windows Vista unterstützt)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries, data = b"", b""
    offset = 6 + 16 * len(pngs)
    for size, png in sorted(pngs.items()):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    path.write_bytes(header + entries + data)


def main() -> None:
    pngs = {s: render_png(s) for s in SIZES}
    write_ico(ROOT / "packaging" / "zotivity.ico", pngs)
    (ROOT / "src" / "zotivity" / "server" / "static" / "img" / "icon.png").write_bytes(pngs[256])
    (ROOT / "packaging" / "zotivity.png").write_bytes(render_png(512))
    print("Symbole erstellt")


if __name__ == "__main__":
    main()
