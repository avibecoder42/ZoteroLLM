"""Zerlegung in überlappende Abschnitte (Chunks) mit Seitenangaben.

Abschnitte folgen Absatz- und Satzgrenzen. Die Grösse wird in Tokens geschätzt
(≈ 4 Zeichen pro Token) – genau genug für die Steuerung, ohne Tokenizer-Abhängigkeit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from zotivity.extract.pdf import PageText

CHARS_PER_TOKEN = 4.0

_SENT_END = re.compile(r"(?<=[.!?…])\s+(?=[\"„“«(\[]?[A-ZÄÖÜ0-9])")
_ABBREVS = {
    "z.", "b.", "u.", "a.", "al.", "vgl.", "bzw.", "s.", "p.", "pp.", "nr.", "ca.", "dr.", "prof.",
    "e.g.", "i.e.", "z.b.", "u.a.", "d.h.", "fig.", "abb.", "tab.", "vol.", "jg.", "hrsg.", "ed.",
    "eds.", "bd.", "kap.", "ch.", "no.", "st.", "vs.", "cf.", "etc.", "ff.", "f.", "inkl.", "evtl.",
}


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN + 0.5))


def _ends_with_abbrev(text: str) -> bool:
    last = text.rsplit(" ", 1)[-1].lower()
    if last in _ABBREVS:
        return True
    # Initialen ("J. Smith") und Ordnungszahlen ("3. Auflage")
    return bool(re.fullmatch(r"[a-zäöü]\.|\d{1,3}\.", last))


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for piece in _SENT_END.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if out and _ends_with_abbrev(out[-1]):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


@dataclass
class Chunk:
    ord: int
    text: str
    page_start: int | None
    page_end: int | None
    page_label: str
    kind: str = "text"
    # Seitenwechsel im Text: [Zeichenposition, PDF-Seite] – für Seitenangaben mitten im Abschnitt
    breaks: list[list[int]] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass
class _Unit:
    page: int
    label: str
    text: str
    para_start: bool

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def _split_long(paragraph: str, max_tokens: int) -> list[str]:
    if estimate_tokens(paragraph) <= max_tokens:
        return [paragraph]
    out: list[str] = []
    for s in split_sentences(paragraph):
        if estimate_tokens(s) <= max_tokens:
            out.append(s)
            continue
        # Überlange "Sätze" (Tabellen, Literaturlisten) an Wortgrenzen teilen
        buf: list[str] = []
        for w in s.split(" "):
            buf.append(w)
            if estimate_tokens(" ".join(buf)) >= max_tokens:
                out.append(" ".join(buf))
                buf = []
        if buf:
            out.append(" ".join(buf))
    return out


def _units(pages: list[PageText], max_unit_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    for page in pages:
        for para in page.text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            for i, sent in enumerate(_split_long(para, max_unit_tokens)):
                units.append(_Unit(page=page.index, label=page.label, text=sent, para_start=(i == 0)))
    return units


def _label_range(first: _Unit, last: _Unit) -> str:
    """Gedruckte Seiten eines Abschnitts („114“ oder „114–115“); "" = ohne Seitenzahl."""
    if not first.label and not last.label:
        return ""
    if not first.label or not last.label or first.label == last.label:
        return first.label or last.label
    return f"{first.label}–{last.label}"


def _join(units: list[_Unit], page: int | None = None) -> tuple[str, list[list[int]]]:
    """Text der Einheiten und die Stellen, an denen eine neue Seite beginnt (page = Seite davor)."""
    out = ""
    breaks: list[list[int]] = []
    for u in units:
        if out:
            out += "\n\n" if u.para_start else " "
        if page is not None and u.page != page:
            breaks.append([len(out), u.page])
        page = u.page
        out += u.text
    return out, breaks


def _make_chunk(ord_: int, units: list[_Unit]) -> Chunk:
    text, breaks = _join(units)
    return Chunk(
        ord=ord_,
        text=text,
        page_start=units[0].page,
        page_end=units[-1].page,
        page_label=_label_range(units[0], units[-1]),
        breaks=breaks,
    )


def chunk_pages(
    pages: list[PageText],
    *,
    chunk_tokens: int = 400,
    overlap_tokens: int = 60,
    min_chunk_tokens: int = 30,
) -> list[Chunk]:
    overlap_tokens = min(overlap_tokens, chunk_tokens // 2)
    units = _units(pages, max_unit_tokens=max(32, chunk_tokens // 2))
    chunks: list[Chunk] = []
    current: list[_Unit] = []
    n_overlap = 0  # wie viele Einheiten am Anfang von `current` aus der Überlappung stammen
    size = 0

    for unit in units:
        if current and size + unit.tokens > chunk_tokens and len(current) > n_overlap:
            chunks.append(_make_chunk(len(chunks), current))
            keep: list[_Unit] = []
            kept = 0
            for u in reversed(current):
                if kept + u.tokens > overlap_tokens:
                    break
                keep.insert(0, u)
                kept += u.tokens
            current = keep
            n_overlap = len(keep)
            size = kept
        current.append(unit)
        size += unit.tokens

    new_units = current[n_overlap:]
    if new_units:
        new_tokens = sum(u.tokens for u in new_units)
        if chunks and new_tokens < min_chunk_tokens:
            last = chunks[-1]
            tail, tail_breaks = _join(new_units, page=last.page_end)
            base = len(last.text) + 1
            last.breaks += [[base + off, page] for off, page in tail_breaks]
            last.text = last.text + " " + tail
            last.page_end = new_units[-1].page
            if last.page_label and new_units[-1].label and not last.page_label.endswith(new_units[-1].label):
                first_label = last.page_label.split("–")[0]
                last.page_label = f"{first_label}–{new_units[-1].label}"
        else:
            chunks.append(_make_chunk(len(chunks), current))
    return chunks


_REF_PATTERNS = re.compile(
    r"\(\d{4}[a-z]?\)|\b(?:19|20)\d{2}[a-z]?[.,;)]|doi[:.]|https?://|\bet al\.|\bpp?\.\s?\d|\bVol\.|\bHrsg\.|\(Eds?\.\)",
    re.IGNORECASE,
)


_REF_HEADING = re.compile(
    r"(?:^|\n\n)\s*(?:\d+\.?\s*)?(?:References|Literatur(?:verzeichnis)?|Bibliograph(?:y|ie)|Works Cited|"
    r"Quellen(?:verzeichnis)?|Literature cited|Références|Bibliografia)\s*(?:\n|$)",
    re.IGNORECASE,
)


def reference_density(text: str) -> float:
    """Treffer typischer Literaturangaben (Jahreszahlen, DOIs, 'et al.' …) pro 1000 Zeichen."""
    if len(text) < 300:
        return 0.0
    return len(_REF_PATTERNS.findall(text)) / (len(text) / 1000)


def mark_references(chunks: list[Chunk]) -> list[Chunk]:
    """Markiert Literaturverzeichnisse als kind='references'. Sie werden nicht eingebettet
    und nicht durchsucht, weil sie Suchtreffer sonst verwässern.

    Kalibriert an der Bibliothek: Fliesstext mit vielen Belegen erreicht Dichten bis ~10,
    Verzeichnisse meist >9 am Dokumentende oder >13 überall."""
    n = len(chunks)
    in_refs = False
    for i, c in enumerate(chunks):
        if c.kind != "text":
            continue
        pos = i / max(1, n - 1)
        d = reference_density(c.text)
        if pos >= 0.5 and _REF_HEADING.search(c.text):
            in_refs = True
        if d >= 13 or (pos >= 0.6 and d >= 9) or (in_refs and d >= 5):
            c.kind = "references"
    return chunks


def make_abstract_chunk(abstract: str) -> Chunk | None:
    abstract = (abstract or "").strip()
    if len(abstract) < 80:
        return None
    return Chunk(ord=-1, text=abstract, page_start=None, page_end=None, page_label="", kind="abstract")
