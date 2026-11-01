"""CSL-Editor: Zitierstile auf zotero.org suchen, übernehmen, bearbeiten, speichern und in Zotero installieren.

- Suche: die Stilliste von zotero.org (styles.json, komprimiert rund 300 KB) wird nur bei einer Suche geladen und
  im Datenordner gespeichert; spätere Suchen fragen mit If-Modified-Since nach (unverändert: 0 Bytes).
- Eigene Stile liegen im Datenordner unter csl-styles/<slug>.csl, Vorversionen unter csl-styles/versions/<slug>/.
- Kennung eigener Stile: http://www.zotero.org/styles/zotivity-<slug>. Das Präfix verhindert, dass ein Original
  (z. B. APA) beim Installieren überschrieben wird – das Zotero-Plugin installiert nur Stile mit diesem Präfix.
- Bearbeitet wird im Browser (citeproc-js, XML-DOM); hier werden nur die Kopfdaten (<info>) gesetzt, damit der
  übrige Text des Stils unverändert bleibt (Kommentare, Reihenfolge, Einrückung).
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from zotivity import __version__, paths

REPO_INDEX_URL = "https://www.zotero.org/styles-files/styles.json"
REPO_STYLE_URL = "https://www.zotero.org/styles/{name}"
REPO_PREFIX = "https://www.zotero.org/styles/"
ID_PREFIX = "http://www.zotero.org/styles/zotivity-"
OWN_PREFIXES = (ID_PREFIX, "http://www.zotero.org/styles/zotllm-")  # eigene Stile aus Versionen bis 1.0.1 behalten ihre Kennung
CSL_NS = "http://purl.org/net/xbiblio/csl"
_NS = "{" + CSL_NS + "}"
INDEX_FRESH_SECONDS = 600  # während einer Sitzung nicht bei jedem Tastendruck nachfragen
MAX_STYLE_BYTES = 2 * 1024 * 1024
KEEP_VERSIONS = 30
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")


class CslError(ValueError):
    """Ungültiger Stil oder nicht erreichbare Quelle – die Meldung ist für die Oberfläche gedacht."""


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": f"Zotivity/{__version__}"})


# -- Kopfdaten ---------------------------------------------------------------------------------------------------
def parse(xml: str) -> ET.Element:
    if len(xml.encode("utf-8")) > MAX_STYLE_BYTES:
        raise CslError("Der Stil ist zu gross.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise CslError(f"Kein gültiges XML: {e}") from e
    if root.tag != _NS + "style":
        raise CslError("Keine CSL-Datei: Das Wurzelelement muss <style> (CSL 1.0) sein.")
    return root


def info(xml: str) -> dict:
    """Titel, Kennung, Format, Fachgebiete, Abhängigkeit und Vorlage eines Stils."""
    root = parse(xml)
    inf = root.find(_NS + "info")
    if inf is None:
        raise CslError("Dem Stil fehlt der Abschnitt <info>.")
    links = {ln.get("rel"): ln.get("href") for ln in inf.findall(_NS + "link")}
    cats = inf.findall(_NS + "category")
    return {
        "title": (inf.findtext(_NS + "title") or "").strip(),
        "id": (inf.findtext(_NS + "id") or "").strip(),
        "format": next((c.get("citation-format") for c in cats if c.get("citation-format")), ""),
        "fields": [c.get("field") for c in cats if c.get("field")],
        "parent": links.get("independent-parent"),
        "template": links.get("template"),
        "updated": (inf.findtext(_NS + "updated") or "").strip(),
        "default_locale": root.get("default-locale") or "",
        "dependent": root.find(_NS + "citation") is None and "independent-parent" in links,
        "own": (inf.findtext(_NS + "id") or "").strip().startswith(OWN_PREFIXES),
    }


def check(xml: str) -> list[str]:
    """Grundprüfung beim Speichern (die genaue Prüfung macht citeproc-js in der Vorschau)."""
    root = parse(xml)
    problems = []
    if root.get("version") != "1.0":
        problems.append("Das Attribut version=\"1.0\" fehlt am Element <style>.")
    meta = info(xml)
    if not meta["title"]:
        problems.append("Der Stil hat keinen Titel.")
    if root.find(_NS + "citation") is None:
        problems.append("Dem Stil fehlt der Abschnitt <citation> (Belege im Text).")
    return problems


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def set_info(xml: str, *, title: str | None = None, style_id: str | None = None, template: str | None = None,
             drop_parent: bool = False) -> str:
    """Kopfdaten im Text ändern, ohne den Rest des Stils anzufassen: Titel, Kennung (+ link rel=self), Vorlage,
    Zeitstempel <updated>."""
    m = re.search(r"(<info\b[^>]*>)(.*?)(</info>)", xml, re.S)
    if not m:
        raise CslError("Dem Stil fehlt der Abschnitt <info>.")
    body = m.group(2)
    indent_m = re.search(r"\n([ \t]+)<", body)
    indent = indent_m.group(1) if indent_m else "    "
    if title is not None:
        body, n = re.subn(r"<title>.*?</title>", f"<title>{_esc(title)}</title>", body, count=1, flags=re.S)
        if not n:
            body = f"\n{indent}<title>{_esc(title)}</title>" + body
        body = re.sub(r"\n?[ \t]*<title-short>.*?</title-short>", "", body, flags=re.S)
    if style_id is not None:
        body, n = re.subn(r"<id>.*?</id>", f"<id>{_esc(style_id)}</id>", body, count=1, flags=re.S)
        if not n:
            body = f"\n{indent}<id>{_esc(style_id)}</id>" + body
        body = re.sub(r'\n?[ \t]*<link\b[^>]*\brel="self"[^>]*/>', "", body)
        body = re.sub(r"(<id>.*?</id>)", rf'\1\n{indent}<link href="{_esc(style_id)}" rel="self"/>', body, count=1, flags=re.S)
    if template is not None:
        body = re.sub(r'\n?[ \t]*<link\b[^>]*\brel="template"[^>]*/>', "", body)
        body = re.sub(r'(<link\b[^>]*\brel="self"[^>]*/>)', rf'\1\n{indent}<link href="{_esc(template)}" rel="template"/>',
                      body, count=1)
    if drop_parent:
        body = re.sub(r'\n?[ \t]*<link\b[^>]*\brel="independent-parent"[^>]*/>', "", body)
    stamp = _now()
    body, n = re.subn(r"<updated>.*?</updated>", f"<updated>{stamp}</updated>", body, count=1, flags=re.S)
    if not n:
        trail = body[len(body.rstrip()):]
        body = body.rstrip() + f"\n{indent}<updated>{stamp}</updated>" + trail
    out =xml[:m.start()] + m.group(1) + body + m.group(3) + xml[m.end():]
    parse(out)  # muss gültig bleiben
    return out


def _with_locale(xml: str, locale: str) -> str:
    """default-locale eines abhängigen Stils (z. B. de-DE) auf die Kopie des eigenständigen Stils übertragen."""
    m = re.search(r"<style\b[^>]*>", xml)
    if not m or not locale:
        return xml
    tag = re.sub(r'\sdefault-locale="[^"]*"', "", m.group(0))
    return xml[:m.start()] + tag[:-1] + f' default-locale="{_esc(locale)}">' + xml[m.end():]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(slug) > 60:  # an einer Wortgrenze kürzen
        slug = slug[:61].rsplit("-", 1)[0]
    return slug or "stil"


# -- Eigene Stile ------------------------------------------------------------------------------------------------
@dataclass
class StyleStore:
    folder: Path

    @classmethod
    def default(cls) -> StyleStore:
        return cls(paths.data_dir() / "csl-styles")

    def _path(self, slug: str) -> Path:
        if not _NAME.match(slug):
            raise CslError("Ungültiger Name des Stils.")
        return self.folder / f"{slug}.csl"

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self.folder.glob("*.csl")) if self.folder.is_dir() else []:
            try:
                meta = info(f.read_text(encoding="utf-8"))
            except (CslError, OSError):
                continue
            out.append({"slug": f.stem, **meta, "modified": f.stat().st_mtime})
        return sorted(out, key=lambda s: -s["modified"])

    def get(self, slug: str) -> str:
        p = self._path(slug)
        if not p.is_file():
            raise KeyError(slug)
        return p.read_text(encoding="utf-8")

    def versions(self, slug: str) -> list[dict]:
        folder = self.folder / "versions" / slug
        files = sorted(folder.glob("*.csl"), reverse=True) if folder.is_dir() else []
        return [{"name": f.stem, "saved_at": f.stat().st_mtime} for f in files]

    def version(self, slug: str, name: str) -> str:
        if not re.fullmatch(r"\d{8}-\d{6}(-\d+)?", name):
            raise KeyError(name)
        p = self.folder / "versions" / slug / f"{name}.csl"
        if not p.is_file():
            raise KeyError(name)
        return p.read_text(encoding="utf-8")

    def create(self, xml: str, title: str, template: str | None) -> tuple[str, str]:
        """Neuer eigener Stil (Kopie): eindeutiger Name, eigene Kennung, Vorlage als link rel=template."""
        base = slugify(title)
        slug, n = base, 2
        while self._path(slug).exists():
            slug, n = f"{base}-{n}", n + 1
        xml = set_info(xml, title=title, style_id=ID_PREFIX + slug, template=template, drop_parent=True)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._path(slug).write_text(xml, encoding="utf-8")
        return slug, xml

    def save(self, slug: str, xml: str) -> str:
        """Speichern; die bisherige Fassung wandert zu den Vorversionen. Kennung und Zeitstempel setzt Zotivity."""
        p = self._path(slug)
        if not p.is_file():
            raise KeyError(slug)
        meta = info(xml)
        xml = set_info(xml, style_id=ID_PREFIX + slug, title=meta["title"] or slug)
        old = p.read_text(encoding="utf-8")
        if old != xml:
            folder = self.folder / "versions" / slug
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            name, n = stamp, 2
            while (folder / f"{name}.csl").exists():
                name, n = f"{stamp}-{n}", n + 1
            (folder / f"{name}.csl").write_text(old, encoding="utf-8")
            for extra in sorted(folder.glob("*.csl"), reverse=True)[KEEP_VERSIONS:]:
                extra.unlink(missing_ok=True)
            p.write_text(xml, encoding="utf-8")
        return xml

    def delete(self, slug: str) -> None:
        p = self._path(slug)
        p.unlink(missing_ok=True)
        folder = self.folder / "versions" / slug
        if folder.is_dir():
            for f in folder.glob("*.csl"):
                f.unlink(missing_ok=True)
            folder.rmdir()


# -- Stilsammlung von zotero.org ------------------------------------------------------------------------------------
class Repository:
    def __init__(self, folder: Path | None = None, client_factory=None):
        self.folder = folder or paths.data_dir() / "csl-cache"
        self.client_factory = client_factory or (lambda: _client())
        self._index: list[dict] | None = None

    @property
    def _meta_path(self) -> Path:
        return self.folder / "styles-index.meta.json"

    def _meta(self) -> dict:
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def index(self) -> tuple[list[dict], dict]:
        """Stilliste: aus dem Zwischenspeicher, sonst (oder wenn älter als 10 Minuten) bedingt neu laden."""
        meta = self._meta()
        cache = self.folder / "styles-index.json"
        fresh = time.time() - meta.get("checked_at", 0) < INDEX_FRESH_SECONDS
        if self._index is not None and fresh:
            return self._index, meta
        if self._index is None and cache.is_file() and fresh:
            self._index = json.loads(cache.read_text(encoding="utf-8"))
            return self._index, meta
        headers = {"If-Modified-Since": meta["last_modified"]} if meta.get("last_modified") and cache.is_file() else {}
        try:
            with self.client_factory() as c:
                r = c.get(REPO_INDEX_URL, headers=headers)
        except httpx.HTTPError as e:
            if cache.is_file():  # offline: letzte bekannte Liste
                self._index = self._index or json.loads(cache.read_text(encoding="utf-8"))
                return self._index, {**meta, "offline": True}
            raise CslError(f"zotero.org ist nicht erreichbar ({e.__class__.__name__}).") from e
        self.folder.mkdir(parents=True, exist_ok=True)
        if r.status_code == 304:
            self._index = self._index or json.loads(cache.read_text(encoding="utf-8"))
        elif r.status_code == 200:
            data = r.json()
            if not isinstance(data, list):
                raise CslError("Unerwartete Antwort von zotero.org.")
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self._index = data
            meta["last_modified"] = r.headers.get("Last-Modified", "")
            meta["downloaded_at"] = time.time()
        else:
            raise CslError(f"zotero.org antwortet mit Fehler {r.status_code}.")
        meta["checked_at"] = time.time()
        self._meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return self._index, meta

    def search(self, query: str, fmt: str = "", field: str = "", limit: int = 60) -> dict:
        styles, meta = self.index()
        words = [w for w in _fold(query).split() if w]
        hits = []
        for s in styles:
            cats = s.get("categories") or {}
            if fmt and cats.get("format") != fmt:
                continue
            if field and field not in (cats.get("fields") or []):
                continue
            hay = _fold(" ".join(filter(None, (s.get("title"), s.get("titleShort"), s.get("name")))))
            if all(w in hay for w in words):
                title = _fold(s.get("title") or "")
                rank = (0 if words and title.startswith(words[0]) else 1, int(bool(s.get("dependent"))), len(title))
                hits.append((rank, s))
        hits.sort(key=lambda x: x[0])
        return {"total": len(hits), "count": len(styles), "offline": bool(meta.get("offline")),
                "results": [_entry(s) for _, s in hits[:limit]]}

    def fetch(self, name: str) -> dict:
        """Stil (und bei abhängigen Stilen den eigenständigen Elternstil) laden."""
        if not _NAME.match(name):
            raise CslError("Ungültiger Stilname.")
        with self.client_factory() as c:
            xml = _get_style(c, REPO_STYLE_URL.format(name=name))
            meta = info(xml)
            parent_xml = None
            if meta["parent"]:
                parent = meta["parent"].replace("http://", "https://", 1)
                if not parent.startswith(REPO_PREFIX):
                    raise CslError("Der Elternstil liegt nicht auf zotero.org.")
                parent_xml = _get_style(c, parent)
        return {"xml": xml, "parent_xml": parent_xml, "info": meta}


def _get_style(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        raise CslError(f"zotero.org ist nicht erreichbar ({e.__class__.__name__}).") from e
    if r.status_code == 404:
        raise CslError("Diesen Stil gibt es auf zotero.org nicht.")
    if r.status_code != 200:
        raise CslError(f"zotero.org antwortet mit Fehler {r.status_code}.")
    if len(r.content) > MAX_STYLE_BYTES:
        raise CslError("Der Stil ist zu gross.")
    return r.text


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def _entry(s: dict) -> dict:
    cats = s.get("categories") or {}
    return {"name": s.get("name"), "title": s.get("title"), "short": s.get("titleShort") or "",
            "format": cats.get("format") or "", "fields": cats.get("fields") or [],
            "dependent": bool(s.get("dependent")), "updated": s.get("updated") or "", "href": s.get("href") or ""}


def editable_copy(xml: str, parent_xml: str | None = None, title: str | None = None) -> tuple[str, str, str]:
    """Grundlage für einen eigenen Stil: bei abhängigen Stilen der Elternstil (mit Titel und Sprache des abhängigen).
    Rückgabe: (XML, Titel, Kennung der Vorlage)."""
    meta = info(xml)
    base = xml
    if meta["dependent"]:
        if not parent_xml:
            raise CslError("Für diesen abhängigen Stil fehlt der Elternstil.")
        base = _with_locale(parent_xml, meta["default_locale"]) if meta["default_locale"] else parent_xml
    return base, title or meta["title"], meta["id"]
