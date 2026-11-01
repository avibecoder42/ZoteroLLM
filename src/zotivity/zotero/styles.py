"""Zitierstile aus Zotero: Liste der installierten Stile (Ordner „styles“ im Zotero-Datenordner) und Auswertung, wie ein
Stil die Seitenangabe setzt – davon hängt ab, wie „o. S.“ in Word-Belege kommt.

Zotero hat keine Schnittstelle, die die installierten Stile aufzählt; sie liegen aber als .csl-Dateien im
Datenordner. Welcher Ordner aktiv ist, steht in den Zotero-Einstellungen (prefs.js des Profils).

Zitierstile (CSL) kennen kein „ohne Seite“. Zwei Wege:
- Stile ohne Seitenbezeichnung vor der Zahl („(Müller 2019: 114)“): „o. S.“ als Seitenangabe – der Stil setzt sein
  eigenes Trennzeichen, auch bei „ebd.: o. S.“.
- Stile mit Seitenbezeichnung („(Müller, 2019, S. 114)“): als Seitenangabe ergäbe das „S. o. S.“, daher „o. S.“ als
  Suffix des Belegs, mit dem Trennzeichen des Stils davor („, o. S.“).
Um das zu erkennen, wird der Kurzbeleg des Stils für einen Musterbeleg nachgebildet (vereinfachte CSL-Auswertung).
"""

from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ZOTERO_STYLE_PREFIX = "http://www.zotero.org/styles/"
DEFAULT_STYLE = ZOTERO_STYLE_PREFIX + "apa"
_NS = "{http://purl.org/net/xbiblio/csl}"

# Platzhalter im nachgebildeten Beleg (NOP = Kennzeichnung ohne Seitenzahl, z. B. „o. S.“)
AUT, DAT, NUM, TIT, LOC, LAB, NOP = "", "", "", "", "", "", ""
_CONTENT = (AUT, DAT, NUM, TIT)
_CLOSE = {"(": ")", "[": "]"}


def normalize_style_id(style: str | None) -> str:
    style = (style or "").strip()
    if not style:
        return DEFAULT_STYLE
    return style if ":" in style else ZOTERO_STYLE_PREFIX + style


# ------------------------------------------------------------------------------------------ Datenordner
def _profile_dirs() -> list[Path]:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "")) / "Zotero" / "Zotero"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Zotero"
    else:
        base = Path.home() / ".zotero" / "zotero"
    dirs: list[Path] = []
    ini = base / "profiles.ini"
    if ini.exists():
        section: dict[str, str] = {}
        sections: list[dict[str, str]] = []
        for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = {}
                sections.append(section)
            elif "=" in line:
                k, _, v = line.partition("=")
                section[k.strip()] = v.strip()
        for s in sorted(sections, key=lambda s: s.get("Default") != "1"):
            if s.get("Path"):
                p = base / s["Path"] if s.get("IsRelative", "1") == "1" else Path(s["Path"])
                dirs.append(p)
    profiles = base / "Profiles"
    if profiles.is_dir():
        extra = sorted((p for p in profiles.iterdir() if (p / "prefs.js").exists()),
                       key=lambda p: (p / "prefs.js").stat().st_mtime, reverse=True)
        dirs += [p for p in extra if p not in dirs]
    return dirs


def data_dir_from_prefs(prefs_text: str) -> Path | None:
    use = re.search(r'user_pref\("extensions\.zotero\.useDataDir",\s*(true|false)\)', prefs_text)
    found = re.search(r'user_pref\("extensions\.zotero\.dataDir",\s*"((?:[^"\\]|\\.)*)"\)', prefs_text)
    if use and use.group(1) == "true" and found:
        try:
            return Path(json.loads(f'"{found.group(1)}"'))
        except ValueError:
            return None
    return None


def zotero_data_dir(store=None) -> Path | None:
    """Aktiver Zotero-Datenordner: aus den Zotero-Einstellungen, sonst der Standardordner ~/Zotero, sonst aus den
    Dateipfaden gespeicherter Anhänge (…/storage/KEY/datei)."""
    for profile in _profile_dirs():
        prefs = profile / "prefs.js"
        if not prefs.exists():
            continue
        path = data_dir_from_prefs(prefs.read_text(encoding="utf-8", errors="replace"))
        if path and path.is_dir():
            return path
        break  # Standardprofil ohne eigenen Datenordner → Standardordner
    default = Path.home() / "Zotero"
    if (default / "styles").is_dir() or (default / "zotero.sqlite").exists():
        return default
    if store is not None:
        row = store.con.execute("SELECT path FROM attachments WHERE path LIKE '%storage%' LIMIT 1").fetchone()
        if row and row[0]:
            parts = Path(row[0]).parts
            if "storage" in parts:
                return Path(*parts[:len(parts) - 1 - parts[::-1].index("storage")])
    return None


# ------------------------------------------------------------------------------------------ Stile
@dataclass
class StyleInfo:
    id: str
    title: str
    format: str  # author-date, numeric, note, author, label
    file: Path
    parent: str | None = None  # abhängiger Stil: ID des eigenständigen Stils
    short: str = ""  # Kurztitel, z. B. „Schreibberatung PH FHNW (Empfehlungen)“

    @property
    def supported(self) -> bool:
        return self.format != "note"  # Fussnotenstile: Belege müssten Fussnoten werden

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "short": self.short, "format": self.format,
                "dependent": bool(self.parent), "supported": self.supported}


_cache: dict[str, tuple[tuple, list[StyleInfo]]] = {}


def _info(path: Path) -> StyleInfo | None:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    info = root.find(f"{_NS}info")
    if info is None:
        return None
    sid = (info.findtext(f"{_NS}id") or "").strip()
    title = (info.findtext(f"{_NS}title") or path.stem).strip()
    fmt = next((c.get("citation-format") for c in info.findall(f"{_NS}category") if c.get("citation-format")), "")
    parent = next((ln.get("href") for ln in info.findall(f"{_NS}link") if ln.get("rel") == "independent-parent"), None)
    short = (info.findtext(f"{_NS}title-short") or "").strip()
    return StyleInfo(id=sid, title=title, format=fmt or "author-date", file=path, parent=parent, short=short) if sid else None


def installed_styles(data_dir: Path | None) -> list[StyleInfo]:
    folder = data_dir / "styles" if data_dir else None
    if not folder or not folder.is_dir():
        return []
    files = sorted(folder.glob("*.csl"))
    stamp = tuple((f.name, f.stat().st_mtime) for f in files)
    cached = _cache.get(str(folder))
    if cached and cached[0] == stamp:
        return cached[1]
    seen: dict[str, StyleInfo] = {}
    for f in files:
        s = _info(f)
        if s and s.id not in seen:
            seen[s.id] = s
    styles = sorted(seen.values(), key=lambda s: s.title.casefold())
    # Abhängige Stile übernehmen das Format ihres eigenständigen Stils, falls dort angegeben
    by_id = {s.id: s for s in styles}
    for s in styles:
        if s.parent and s.parent in by_id and by_id[s.parent].format:
            s.format = by_id[s.parent].format
    _cache[str(folder)] = (stamp, styles)
    return styles


def style_xml(style_id: str, data_dir: Path | None) -> bytes | None:
    """CSL eines installierten Stils; bei abhängigen Stilen der eigenständige Stil."""
    by_id = {s.id: s for s in installed_styles(data_dir)}
    s = by_id.get(normalize_style_id(style_id))
    if s and s.parent:
        s = by_id.get(s.parent, s)
    try:
        return s.file.read_bytes() if s else None
    except OSError:
        return None


# ------------------------------------------------------------------------------------------ Seitenangabe im Stil
@dataclass
class LocatorStyle:
    """Wie ein Stil die Seite im Kurzbeleg setzt (aus dem nachgebildeten Musterbeleg)."""
    delimiter: str = ", "  # vor der Seitenangabe
    label: bool = True  # Seitenbezeichnung („S.“, „p.“) vor der Zahl?
    author_date: str = ", "  # zwischen Autor und Jahr
    prefix: str = "("
    suffix: str = ")"
    found: bool = False  # aus dem Stil ermittelt (sonst Vorgabe wie APA)
    # Musterbelege mit Platzhaltern (siehe preview): mit Seite, ohne Seite, „o. S.“ als Seitenangabe
    sample_page: str = f"{AUT}, {DAT}, {LAB} {LOC}114"
    sample_none: str = f"{AUT}, {DAT}"
    sample_np: str = f"{AUT}, {DAT}, {LAB} {LOC}{NOP}"

    @property
    def no_page_mode(self) -> str:
        """„locator“: o. S. als Seitenangabe (Stil setzt Trennzeichen) – „suffix“: als Suffix mit Trennzeichen."""
        return "suffix" if self.label else "locator"

    def suffix_for(self, text: str) -> str:
        """Suffix „, o. S.“ – setzt der Stil die Seite in Klammern („(S. 114)“), wird auch die Klammer geschlossen."""
        if not text:
            return ""
        close = "".join(_CLOSE[ch] for ch in self.delimiter if ch in _CLOSE and _CLOSE[ch] not in self.delimiter)
        return f"{self.delimiter}{text}{close}"

    def as_dict(self) -> dict:
        return {"delimiter": self.delimiter, "label": self.label, "mode": self.no_page_mode, "found": self.found}


# ------------------------------------------------------------------------------------------ Namen im Kurzbeleg
_AND_TERM = {"de": "und", "en": "and"}
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


@dataclass
class NameStyle:
    """Wie ein Stil die Autorinnen und Autoren im Kurzbeleg setzt (cs:name im Kurzbeleg), z. B. FHNW „Gong/Li“,
    APA „Gong & Li“, ab drei Namen „Gong et al.“. Ohne lesbaren Stil die Vorgabe wie APA."""
    delimiter: str = ", "
    and_: str = "symbol"  # "", "text" („und“) oder "symbol" („&“)
    delimiter_precedes_last: str = "contextual"
    et_al_min: int = 3
    et_al_use_first: int = 1
    et_al_term: str = "et al."
    and_term: str = ""  # aus dem Stil, sonst „und“/„and“ je Sprache
    found: bool = False

    def format(self, families: list[str], language: str = "de") -> str:
        names = [f for f in families if f]
        if not names:
            return ""
        if self.et_al_min and len(names) >= self.et_al_min and self.et_al_use_first:
            shown = names[:self.et_al_use_first]
            # delimiter-precedes-et-al „contextual“: Trennzeichen nur, wenn mehr als ein Name steht
            sep = self.delimiter if len(shown) > 1 else " "
            return self.delimiter.join(shown) + sep + self.et_al_term
        if len(names) == 1:
            return names[0]
        word = {"text": self.and_term or _AND_TERM.get(language, "and"), "symbol": "&"}.get(self.and_)
        if not word:
            return self.delimiter.join(names)
        before_last = self.delimiter_precedes_last == "always" or (
            self.delimiter_precedes_last == "contextual" and len(names) > 2)
        return self.delimiter.join(names[:-1]) + (self.delimiter.rstrip() + " " if before_last else " ") + word + " " + names[-1]


def _locale_term(root: ET.Element, name: str, language: str) -> str:
    """Begriff aus den Sprachangaben des Stils (cs:locale), passend zur Sprache oder ohne Sprache."""
    for loc in root.findall(f"{_NS}locale"):
        lang = loc.get(_XML_LANG, "")
        if lang and not lang.lower().startswith(language.lower()):
            continue
        for term in loc.iter(f"{_NS}term"):
            if term.get("name") == name and term.get("form", "long") == "long" and (term.text or "").strip():
                return term.text.strip()
    return ""


def analyze_names(xml: bytes | None, language: str = "de") -> NameStyle:
    """Namensregeln des Kurzbelegs: cs:name der ersten Autoren-Angabe in cs:citation (auch in Makros); Optionen,
    die dort fehlen, erbt cs:name von cs:citation bzw. cs:style."""
    parsed = _citation_layout(xml) if xml else None
    if not parsed:
        return NameStyle()
    root, layout = parsed
    citation = root.find(f"{_NS}citation")
    macros = {m.get("name"): m for m in root.findall(f"{_NS}macro")}

    def find(el: ET.Element, depth: int = 0) -> ET.Element | None:
        for child in el.iter():
            tag = child.tag.replace(_NS, "")
            if tag == "names" and "author" in child.get("variable", "").split():
                return child
            if tag == "text" and child.get("macro") in macros and depth < 6:
                hit = find(macros[child.get("macro")], depth + 1)
                if hit is not None:
                    return hit
        return None

    names = find(layout)
    name = names.find(f"{_NS}name") if names is not None else None
    if name is None:
        return NameStyle()

    def opt(attr: str, inherited: str | None = None) -> str | None:
        if name.get(attr) is not None:
            return name.get(attr)
        for holder in (citation, root):
            if holder is not None and holder.get(inherited or attr) is not None:
                return holder.get(inherited or attr)
        return None

    return NameStyle(
        delimiter=opt("delimiter", "name-delimiter") or ", ",
        and_=opt("and") or "",
        delimiter_precedes_last=opt("delimiter-precedes-last") or "contextual",
        et_al_min=int(opt("et-al-min") or 0),
        et_al_use_first=int(opt("et-al-use-first") or 0),
        et_al_term=_locale_term(root, "et-al", language) or "et al.",
        and_term=_locale_term(root, "and", language),
        found=True,
    )


class _Csl:
    """Sehr vereinfachte Auswertung des Kurzbelegs (cs:citation) für einen Musterbeleg: Zeitschriftenartikel,
    eine Person, Jahr, erste Erwähnung, Seitenangabe als „page“."""

    def __init__(self, root: ET.Element, locator: str | None):
        self.macros = {m.get("name"): m for m in root.findall(f"{_NS}macro")}
        self.vars = {"author": AUT, "issued": DAT, "citation-number": NUM, "title": TIT, "title-short": TIT}
        if locator is not None:
            self.vars["locator"] = locator
        self.locator = locator

    def present(self, var: str) -> bool:
        return bool(self.vars.get(var)) or var in ("author", "issued", "title", "container-title")

    def test(self, el: ET.Element) -> bool:
        results: list[bool] = []
        for attr, value in el.attrib.items():
            vals = value.split()
            if attr == "variable":
                results += [self.present(v) for v in vals]
            elif attr == "type":
                results += [v == "article-journal" for v in vals]
            elif attr == "position":
                results += [v == "first" for v in vals]
            elif attr == "locator":
                results += [self.locator is not None and v == "page" for v in vals]
            elif attr == "is-numeric":
                results += [v == "locator" and bool(self.locator) and self.locator[:1].isdigit() for v in vals]
            elif attr in ("is-uncertain-date", "disambiguate"):
                results += [False for _ in vals]
        match = el.get("match", "all")
        if not results:
            return True
        return all(results) if match == "all" else any(results) if match == "any" else not any(results)

    def _branch(self, choose: ET.Element) -> ET.Element | None:
        for branch in choose:
            if branch.tag.replace(_NS, "") == "else" or self.test(branch):
                return branch
        return None

    def _children(self, el: ET.Element):
        """Kinder eines Elements; cs:choose ist durchlässig (die Kinder des gewählten Zweigs zählen als Kinder der
        umgebenden Gruppe – deren Trennzeichen gilt auch zwischen ihnen)."""
        for child in el:
            if child.tag.replace(_NS, "") == "choose":
                branch = self._branch(child)
                if branch is not None:
                    yield from self._children(branch)
            else:
                yield child

    def render(self, el: ET.Element) -> tuple[str, bool, bool]:
        """(Text, ruft Variable auf, gibt Variable aus) – für die Unterdrückung leerer Gruppen."""
        tag = el.tag.replace(_NS, "")
        out, called, rendered = "", False, False
        if tag in ("group", "layout", "macro"):
            parts = []
            for child in self._children(el):
                t, c, r = self.render(child)
                called, rendered = called or c, rendered or r
                if t:
                    parts.append(t)
            if tag == "group" and called and not rendered:
                return "", True, False
            out = el.get("delimiter", "").join(parts) if tag == "group" else "".join(parts)
        elif tag == "text":
            if el.get("macro") in self.macros:
                out, called, rendered = self.render(self.macros[el.get("macro")])
            elif el.get("variable"):
                called = True
                out = self.vars.get(el.get("variable"), "")
                rendered = bool(out)
            elif el.get("term") in ("page", "pages"):
                out = LAB if self.locator is not None else ""
            elif el.get("value"):
                out = el.get("value")
        elif tag == "label":
            out = LAB if el.get("variable") == "locator" and self.locator is not None else ""
        elif tag == "names":
            called = True
            if "author" in el.get("variable", "").split():
                out = AUT
            else:  # andere Rollen fehlen beim Musterbeleg: Ersatz (cs:substitute) wie im Stil
                sub = el.find(f"{_NS}substitute")
                for child in self._children(sub) if sub is not None else []:
                    out = self.render(child)[0]
                    if out:
                        break
            rendered = bool(out)
        elif tag == "date":
            called = True
            out = DAT if el.get("variable") == "issued" else ""
            rendered = bool(out)
        elif tag == "number":
            called = True
            out = self.vars.get(el.get("variable"), "")
            rendered = bool(out)
        if out:
            out = f"{el.get('prefix', '')}{out}{el.get('suffix', '')}"
        return out, called, rendered


def _citation_layout(xml: bytes) -> tuple[ET.Element, ET.Element] | None:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    layout = root.find(f"{_NS}citation/{_NS}layout")
    return (root, layout) if layout is not None else None


def analyze_locator(xml: bytes | None) -> LocatorStyle:
    """Seitenangabe im Kurzbeleg eines Stils ermitteln; ohne lesbaren Stil die Vorgabe (wie APA: „, S. 114“)."""
    parsed = _citation_layout(xml) if xml else None
    if not parsed:
        return LocatorStyle()
    root, layout = parsed
    bare = _strip_affixes(layout)
    body, _, _ = _Csl(root, LOC + "114").render(bare)
    none, _, _ = _Csl(root, None).render(bare)
    np_body, _, _ = _Csl(root, LOC + NOP).render(bare)
    prefix, suffix = layout.get("prefix", ""), layout.get("suffix", "")
    if LOC not in body:  # Stil setzt keine Seitenangaben in den Kurzbeleg
        return LocatorStyle(prefix=prefix, suffix=suffix, sample_page=none, sample_none=none, sample_np=none)
    at = body.index(LOC)
    label = LAB in body[:at] and body.rfind(LAB, 0, at) > max((body.rfind(m, 0, at) for m in _CONTENT), default=-1)
    stop = body.rfind(LAB, 0, at) if label else at
    before = body[:stop]
    last = max(((before.rfind(m), m) for m in _CONTENT), default=(-1, ""))
    delimiter = before[last[0] + 1:] if last[0] >= 0 else ", "
    delimiter = re.split(r"[)\]]", delimiter)[-1]  # schliessende Klammer gehört zum Jahr, nicht zur Seite
    author_date = ", "
    if AUT in body and DAT in body and body.index(AUT) < body.index(DAT):
        author_date = body[body.index(AUT) + 1:body.index(DAT)] or " "
    return LocatorStyle(delimiter=delimiter or " ", label=label, author_date=author_date, prefix=prefix,
                        suffix=suffix, found=True, sample_page=body, sample_none=none, sample_np=np_body)


def _strip_affixes(layout: ET.Element) -> ET.Element:
    el = ET.Element(layout.tag)
    el.extend(list(layout))
    return el


def preview(loc: LocatorStyle, language: str, no_page: str) -> dict:
    """Musterbelege für die Einstellungen (vereinfacht nachgebildet): mit Seite und ohne Seitenzahl – so, wie
    Zotivity „o. S.“ in den Zotero-Beleg setzt (Seitenangabe bzw. Suffix)."""
    term = "S." if language == "de" else "p."

    def fill(s: str) -> str:
        s = s.replace(AUT, "Gillingham").replace(DAT, "2019").replace(NUM, "1").replace(TIT, "Titel")
        s = s.replace(LAB, term).replace(LOC, "").replace(NOP, no_page)
        return loc.prefix + s + loc.suffix

    if not no_page:
        without = fill(loc.sample_none)
    elif loc.no_page_mode == "locator":
        without = fill(loc.sample_np)
    else:
        without = fill(loc.sample_none + loc.suffix_for(NOP))
    return {"page": fill(loc.sample_page), "no_page": without}
