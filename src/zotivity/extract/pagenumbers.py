"""Gedruckte Seitenzahlen erkennen – zitiert wird nach dem Druck (Kopf-/Fusszeile), nicht nach der Seite der Datei.

Vorgehen je Dokument:
1. Kopf- und Fusszeilen jeder Seite nach Zahlen absuchen (Blöcke am oberen/unteren Rand, kurze Rand-Blöcke).
2. Eine Zählung gilt erst, wenn sie über mehrere Seiten aufgeht: Für jede Zahl n auf PDF-Seite i stimmt der
   Abstand k = n − i. Der Abstand mit den meisten Seiten gewinnt. Jahrgänge, Jahreszahlen und Heftnummern stehen
   zwar auf vielen Seiten, ergeben aber keinen gleichbleibenden Abstand und fallen so heraus.
3. Seiten ohne sichtbare Zahl innerhalb der erkannten Folge (typisch: erste Artikelseite) bekommen die Zahl aus der
   Folge; vorgeschaltete Deckblätter ausserhalb der Spanne laut Zotero („Seiten“) bekommen keine.
4. Ohne erkennbare Folge: Seitenbeschriftungen der PDF (nur wenn sie mehr sind als 1, 2, 3 …), sonst die Spanne
   laut Zotero, wenn die Seitenzahl der Datei genau dazu passt – sonst keine Seitenzahl („o. S.“).
Römische Zahlen (Vorspann von Büchern) werden ebenso erkannt, aber nur vor dem arabisch gezählten Teil verwendet.
"""

from __future__ import annotations

import math
import re
from collections import Counter

MARGIN = 0.11  # oberer/unterer Rand als Anteil der Seitenhöhe
MAX_BLOCK_CHARS = 160
_ARABIC = re.compile(r"(?<![\w./:-])(\d{1,5})(?![\w/]|[.,]\d)")
_ROMAN_ONLY = re.compile(r"^\s*(?:(?:seite|page|s\.|p\.)\s*)?([ivxlcdm]{1,8})\s*$", re.IGNORECASE)
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def roman_value(s: str) -> int | None:
    s = s.lower()
    if not s or any(ch not in _ROMAN for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        v = _ROMAN[ch]
        total += -v if i + 1 < len(s) and _ROMAN[s[i + 1]] > v else v
    return total if 0 < total <= 400 and to_roman(total) == s else None


def to_roman(n: int) -> str:
    out = ""
    for v, sym in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"),
                   (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += sym
            n -= v
    return out


def margin_candidates(blocks: list[tuple[float, float, float, float, str]], height: float) -> list[tuple[str, int]]:
    """Zahlen aus Blöcken am Seitenrand: [("a", 114), ("r", 12)] – a = arabisch, r = römisch."""
    out: list[tuple[str, int]] = []
    n = len(blocks)
    for i, (_x0, y0, _x1, y1, text) in enumerate(blocks):
        text = (text or "").strip()
        if not text or len(text) > MAX_BLOCK_CHARS:
            continue
        at_edge = (height and (y1 <= height * MARGIN or y0 >= height * (1 - MARGIN))) or (
            (i < 2 or i >= n - 2) and len(text) <= 80)
        if not at_edge:
            continue
        for m in _ARABIC.finditer(text):
            v = int(m.group(1))
            if 0 < v < 100000:
                out.append(("a", v))
        rm = _ROMAN_ONLY.match(text)
        if rm and (v := roman_value(rm.group(1))):
            out.append(("r", v))
    return out


def parse_page_range(pages: str | None) -> tuple[int, int] | None:
    """Zotero-Feld „Seiten“: „114–126“, „114-26“ (verkürzt) → (114, 126); sonst None."""
    m = re.match(r"^\s*(\d{1,5})\s*(?:[-–—]\s*(\d{1,5}))?\s*$", pages or "")
    if not m:
        return None
    start = int(m.group(1))
    if not m.group(2):
        return start, start
    end_s = m.group(2)
    end = int(end_s)
    if end < start and len(end_s) < len(m.group(1)):  # „114-26“ → 126
        end = int(m.group(1)[: len(m.group(1)) - len(end_s)] + end_s)
    return (start, end) if end >= start else None


def _best_offset(cands: list[list[int]], n: int, prefer_not: int | None = None) -> tuple[int | None, int]:
    votes: Counter[int] = Counter()
    for i, values in enumerate(cands):
        for k in {v - i for v in values}:
            votes[k] += 1
    if not votes:
        return None, 0
    ranked = votes.most_common()
    best_k, support = ranked[0]
    # Gleich starke Alternativen (z. B. „Seite 3 von 14“ eines Downloadportals neben der Heftpaginierung):
    # die Zählung bevorzugen, die nicht bloss die Dateiseite wiederholt
    if prefer_not is not None and best_k == prefer_not:
        for k, s in ranked[1:]:
            if s >= 0.8 * support:
                best_k, support = k, s
                break
    return best_k, support


_HEX_STRING = re.compile(r"<([0-9A-Fa-f\s]{2,})>")


def _decode_pdf_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", "replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", "replace")
    return raw.decode("latin-1")


def _hex_to_text(m: re.Match) -> str:
    digits = re.sub(r"\s", "", m.group(1))
    if len(digits) % 2:  # PDF: eine fehlende letzte Ziffer zählt als 0
        digits += "0"
    return _decode_pdf_bytes(bytes.fromhex(digits))


def clean_pdf_label(label: str | None) -> str:
    """Seitenbeschriftung aus der PDF lesbar machen. PyMuPDF gibt Beschriftungen, die in der PDF als Hex-Text
    stehen, teils roh zurück – „<FEFF0032>“ ist UTF-16 für „2“; auch Bereiche wie „<FEFF0037>–<FEFF0038>“."""
    s = _HEX_STRING.sub(_hex_to_text, label or "")
    if s.startswith("þÿ") or s.startswith("ÿþ"):  # UTF-16 mit BOM, als Latin-1 gelesen
        s = _decode_pdf_bytes(s.encode("latin-1", "replace"))
    return s.replace("﻿", "").replace("\x00", "").strip()


def detect_page_labels(cands: list[list[tuple[str, int]]], pdf_labels: list[str] | None = None,
                       page_range: tuple[int, int] | None = None) -> tuple[list[str], str]:
    """Gedruckte Seitenzahl je PDF-Seite ("" = keine). Rückgabe (Beschriftungen, Quelle) mit Quelle
    „kopfzeile“, „pdf“, „zotero“ oder „“ (keine Zählung erkennbar)."""
    n = len(cands)
    labels = [""] * n
    if not n:
        return labels, ""
    arabic = [[v for t, v in c if t == "a"] for c in cands]
    need = max(1 if n == 1 else 2, math.ceil(0.3 * n))
    k, support = _best_offset(arabic, n, prefer_not=1)
    source = ""
    first_arabic = n
    if k is not None and (support >= need or (n == 1 and page_range and page_range[0] == k)):
        hits = [i for i, values in enumerate(arabic) if k + i in values]
        first, last = hits[0], hits[-1]
        lo, hi = (page_range if page_range and page_range[0] <= k + first <= page_range[1] + 2 else (None, None))
        for i in range(n):
            v = k + i
            if v < 1:
                continue
            inside = first <= i <= last
            if lo is not None:
                ok = inside or lo <= v <= max(hi, k + last)
            else:  # ohne Spanne aus Zotero: höchstens eine Seite vor und zwei nach der Folge ergänzen
                ok = inside or first - 1 <= i <= last + 2
            if ok:
                labels[i] = str(v)
        first_arabic = next((i for i, x in enumerate(labels) if x), n)
        source = "kopfzeile"
    # Römisch gezählter Vorspann
    roman = [[v for t, v in c if t == "r"] for c in cands[:first_arabic]]
    if roman and any(roman):
        rk, rsupport = _best_offset(roman, len(roman))
        if rk is not None and rsupport >= 2:
            hits = [i for i, values in enumerate(roman) if rk + i in values]
            for i in range(max(0, hits[0] - 1), min(first_arabic, hits[-1] + 1)):
                if not labels[i] and rk + i >= 1:
                    labels[i] = to_roman(rk + i)
            source = source or "kopfzeile"
    if source:
        return labels, source
    # Seitenbeschriftungen der PDF – nur, wenn sie mehr aussagen als die Dateiseite
    if pdf_labels and len(pdf_labels) == n:
        meaningful = [lab for i, lab in enumerate(pdf_labels) if lab and lab != str(i + 1)]
        if len(meaningful) >= max(1, n // 2):
            return [lab or "" for lab in pdf_labels], "pdf"
    # Spanne laut Zotero, wenn die Dateiseiten genau dazu passen
    if page_range and page_range[1] - page_range[0] + 1 == n:
        return [str(page_range[0] + i) for i in range(n)], "zotero"
    return labels, ""
