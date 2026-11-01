"""Test-Doubles: simulierte lokale Zotero-API, Schlüsselspeicher und LLM."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx
import keyring.backend
import pymupdf

from zotivity.llm.base import ChatModel, StreamEvent, Usage


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        import keyring.errors

        if (service, username) not in self.data:
            raise keyring.errors.PasswordDeleteError("nicht vorhanden")
        del self.data[(service, username)]


def make_pdf(path: Path, pages: list[str], first_page: int | None = 1, header: str = "",
             unnumbered: tuple[int, ...] = ()) -> Path:
    """Test-PDF; first_page: gedruckte Seitenzahl der ersten Seite in der Fusszeile (None = ohne Seitenzahlen),
    header: Kopfzeile auf jeder Seite, unnumbered: Seiten (0-basiert) ohne sichtbare Seitenzahl."""
    doc = pymupdf.open()
    for i, text in enumerate(pages):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(60, 60, 540, 780), text, fontsize=10)
        if header:
            page.insert_text((60, 35), header, fontsize=8)
        if first_page is not None and i not in unnumbered:
            page.insert_text((290, 815), str(first_page + i), fontsize=9)
    doc.save(path)
    doc.close()
    return path


# Kleiner Ausschnitt des Zotero-Schemas (GET /api/schema): eine Standardart, zwei Arten mit Beispiel, eine neue ohne
SCHEMA = {
    "version": 44,
    "itemTypes": [
        {"itemType": "book", "fields": [{"field": "title"}, {"field": "date"}], "creatorTypes": [{"creatorType": "author", "primary": True}]},
        {"itemType": "case", "fields": [{"field": "caseName", "baseField": "title"}, {"field": "court", "baseField": "authority"},
                                        {"field": "dateDecided", "baseField": "date"}, {"field": "reporter"},
                                        {"field": "reporterVolume", "baseField": "volume"}, {"field": "firstPage", "baseField": "pages"}],
         "creatorTypes": [{"creatorType": "author", "primary": True}, {"creatorType": "counsel"}]},
        {"itemType": "artwork", "fields": [{"field": "title"}, {"field": "artworkMedium", "baseField": "medium"}, {"field": "date"},
                                           {"field": "archive"}, {"field": "artworkSize"}],
         "creatorTypes": [{"creatorType": "artist", "primary": True}, {"creatorType": "contributor"}]},
        {"itemType": "hologram", "fields": [{"field": "title"}, {"field": "date"}, {"field": "studio", "baseField": "publisher"}],
         "creatorTypes": [{"creatorType": "holographer", "primary": True}]},
        {"itemType": "note", "fields": [], "creatorTypes": []},
    ],
    "csl": {
        "types": {"book": ["book"], "legal_case": ["case"], "graphic": ["artwork"]},
        "fields": {"text": {"title": ["title"], "container-title": ["publicationTitle", "reporter"], "authority": ["authority"],
                            "volume": ["volume"], "page": ["pages"], "medium": ["medium"], "archive": ["archive"],
                            "publisher": ["publisher"], "dimensions": ["artworkSize"]},
                   "date": {"issued": "date"}},
        "names": {"author": "author", "contributor": "contributor"},
    },
    "locales": {"de": {"itemTypes": {"book": "Buch", "case": "Gerichtsentscheidung", "artwork": "Kunstwerk", "hologram": "Hologramm"}},
                "en-US": {"itemTypes": {"book": "Book", "case": "Case", "artwork": "Artwork", "hologram": "Hologram"}}},
}


class FakeZotero:
    """Minimaler Nachbau der lokalen Zotero-10-API (Lesen + Schreiben)."""

    SERVER_ID = "SRV123456789"

    def __init__(self, storage: Path, lib: str = "users/0", versioned: bool = True, group_name: str = "Gruppe"):
        """versioned=False bildet Gruppenbibliotheken in Zotero 10 nach: alle Versionen sind 0."""
        self.storage = storage
        self.lib = lib
        self.versioned = versioned
        self.group_name = group_name
        self.version = 10
        self.items: dict[str, dict] = {}
        self.collections: dict[str, dict] = {}
        self.local_key = "LOCALKEY123"
        self.authorized = True
        self.remember = True  # „Entscheidung merken“ im Zotero-Dialog
        self.plugin = True  # Zotivity-Plugin installiert (Schnittstelle /zotivity/uris)
        self.plugin_version = (0, 10)  # ab 0.10: Stile installieren (/zotivity/styles/install)
        self.installed_styles: dict[str, str] = {}
        self.schema = SCHEMA
        self.writes: list[dict] = []
        self.json_item_requests = 0  # Anfragen mit vollem JSON (lösen in Zotero MD5-Berechnungen aus)
        self._next = 0

    def _ver(self) -> int:
        return self.version if self.versioned else 0

    def _key(self) -> str:
        self._next += 1
        return f"N{self._next:07d}"

    def add_collection(self, key, name, parent=None):
        self.collections[key] = {"key": key, "version": self.version,
                                 "data": {"key": key, "name": name, "parentCollection": parent or False},
                                 "meta": {"numItems": 0}}

    def add_item(self, key, title, creators="Muster", year="2021", abstract="", collections=(), item_type="journalArticle"):
        self.version += 1
        self.items[key] = {
            "key": key, "version": self._ver(),
            "data": {"key": key, "itemType": item_type, "title": title, "abstractNote": abstract,
                     "creators": [{"creatorType": "author", "lastName": creators, "firstName": "A."}],
                     "date": year, "collections": list(collections), "tags": []},
            "meta": {"creatorSummary": creators, "parsedDate": year},
        }

    def add_pdf(self, key, parent, pages: list[str], **pdf_options):
        """pdf_options wie make_pdf: first_page (gedruckte erste Seite, None = ohne), header, unnumbered."""
        self.version += 1
        folder = self.storage / key
        folder.mkdir(parents=True, exist_ok=True)
        path = make_pdf(folder / f"{key}.pdf", pages, **pdf_options)
        self.items[key] = {
            "key": key, "version": self._ver(),
            "data": {"key": key, "itemType": "attachment", "parentItem": parent, "linkMode": "imported_file",
                     "contentType": "application/pdf", "title": "PDF", "filename": path.name,
                     # wie Zotero: MD5 des Dateiinhalts
                     "md5": hashlib.md5(path.read_bytes()).hexdigest(), "mtime": 1},
            "links": {"enclosure": {"href": path.as_uri(), "type": "application/pdf"}},
        }

    def add_snapshot(self, key, parent, html: str):
        """Webseiten-Schnappschuss (HTML) wie von Zotero gespeichert."""
        self.version += 1
        folder = self.storage / key
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "seite.html"
        path.write_text(html, encoding="utf-8")
        self.items[key] = {
            "key": key, "version": self._ver(),
            "data": {"key": key, "itemType": "attachment", "parentItem": parent, "linkMode": "imported_url",
                     "contentType": "text/html", "title": "Snapshot", "filename": path.name,
                     "md5": hashlib.md5(path.read_bytes()).hexdigest(), "mtime": 1},
            "links": {"enclosure": {"href": path.as_uri(), "type": "text/html"}},
        }

    def add_file(self, key, parent, path: Path, content_type: str):
        """Beliebige gespeicherte Datei (z. B. Word) als Anhang."""
        self.version += 1
        self.items[key] = {
            "key": key, "version": self._ver(),
            "data": {"key": key, "itemType": "attachment", "parentItem": parent, "linkMode": "imported_file",
                     "contentType": content_type, "title": path.name, "filename": path.name,
                     "md5": hashlib.md5(path.read_bytes()).hexdigest(), "mtime": 1},
            "links": {"enclosure": {"href": path.as_uri(), "type": content_type}},
        }

    def add_link(self, key, parent, url="https://example.org"):
        self.version += 1
        self.items[key] = {"key": key, "version": self._ver(),
                           "data": {"key": key, "itemType": "attachment", "parentItem": parent,
                                    "linkMode": "linked_url", "url": url, "title": "Link", "contentType": ""}}

    def add_note(self, key, parent):
        self.version += 1
        self.items[key] = {"key": key, "version": self._ver(),
                           "data": {"key": key, "itemType": "note", "parentItem": parent, "note": "<p>x</p>"}}

    # -- Transport -----------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _resp(self, status, body=None, headers=None, text=None):
        h = {"Zotero-Server-ID": self.SERVER_ID, "Zotero-API-Version": "3", **(headers or {})}
        if text is not None:
            return httpx.Response(status, text=text, headers=h)
        return httpx.Response(status, json=body, headers=h)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = request.url.params
        if path == "/connector/ping":
            return httpx.Response(200, text="Zotero is running", headers={"X-Zotero-Version": "10.0.5"})
        if path == "/api/":
            return self._resp(200, text="Nothing to see here.")
        if path == "/api/schema":
            return self._resp(200, self.schema)
        if request.method != "GET":
            # Wie Zotero 10 (LocalAPIEndpoint._validateServerID): jede schreibende Anfrage braucht die Server-ID
            sid = request.headers.get("Zotero-Server-ID")
            if not sid:
                return self._resp(428, text="Zotero-Server-ID not provided")
            if sid != self.SERVER_ID:
                return self._resp(412, text="Zotero-Server-ID does not match this server")
        if path == "/zotivity/uris":
            # Schnittstelle des Zotivity-Plugins: URIs, wie sie das Word-Plugin speichert
            if not self.plugin:
                return self._resp(404, text="No endpoint found")
            refs = json.loads(request.content or b"{}").get("items", [])
            return self._resp(200, {"uris": {r: f"http://zotero.org/users/local/abcd1234/items/{r.split(':')[1]}"
                                             for r in refs}})
        if path == "/zotivity/styles/install":
            # Plugin ab 1.0.0: eigenen Stil installieren (nur mit X-Zotivity und Zotivity-Kennung, wie im Plugin)
            if not self.plugin or self.plugin_version < (0, 10):
                return self._resp(404, text="No endpoint found")
            if request.headers.get("X-Zotivity") != "1":
                return self._resp(403, text="X-Zotivity header required")
            style = json.loads(request.content or b"{}").get("style", "")
            m = re.search(r"<id>\s*([^<]+?)\s*</id>", style)
            if not m or not m.group(1).startswith("http://www.zotero.org/styles/zotivity-"):
                return self._resp(400, {"error": "Nur eigene Stile aus Zotivity"})
            self.installed_styles[m.group(1)] = style
            return self._resp(200, {"installed": m.group(1)})
        if path == "/api/local/authorize":
            if not json.loads(request.content or b"{}").get("appName"):
                return self._resp(400, text="appName is required")
            return self._resp(200, {"key": self.local_key, "remember": self.remember}) if self.authorized \
                else self._resp(403, {"denied": True})
        if request.method != "GET":
            return self._write(request)
        lib = re.escape(self.lib)
        if path == "/api/users/0/groups":
            if self.lib.startswith("groups/"):
                return self._resp(200, [{"id": int(self.lib.split("/")[1]), "data": {"name": self.group_name}}])
            return self._resp(200, [])
        m = re.fullmatch(rf"/api/{lib}/collections", path)
        if m:
            return self._resp(200, list(self.collections.values()))
        m = re.fullmatch(rf"/api/{lib}/(?:collections/(\w+)/)?items(/top)?", path)
        if m:
            items = list(self.items.values())
            if m.group(1):
                items = [i for i in items if m.group(1) in i["data"].get("collections", [])]
            # Suchsyntax wie Zotero: mehrere itemType-Parameter UND-verknüpft, "-" = Negation, "||" = ODER
            for spec in params.get_list("itemType"):
                neg = spec.startswith("-")
                wanted = set(spec.lstrip("-").split("||"))
                items = [i for i in items if (i["data"]["itemType"] in wanted) != neg]
            if params.get("itemKey"):
                keys = set(params["itemKey"].split(","))
                items = [i for i in items if i["key"] in keys]
            if params.get("since"):
                items = [i for i in items if i["version"] > int(params["since"])]
            items.sort(key=lambda i: i["version"])
            start, limit = int(params.get("start", 0)), params.get("limit")
            page = items[start: start + int(limit)] if limit else items[start:]
            headers = {"Last-Modified-Version": str(self._ver()), "Total-Results": str(len(items))}
            if params.get("format") == "keys":
                return self._resp(200, headers=headers, text="\n".join(i["key"] for i in page))
            if params.get("format") == "csljson":
                return self._resp(200, {"items": [self._csl(i) for i in page]})
            if params.get("format") == "bib":
                entries = "".join(f'<div class="csl-entry">{self._csl(i)["author"][0]["family"]}, A. '
                                  f'({i["data"].get("date")}). <i>{i["data"]["title"]}</i>.</div>' for i in page)
                return self._resp(200, text=f'<div class="csl-bib-body">{entries}</div>')
            self.json_item_requests += 1
            return self._resp(200, page, headers=headers)
        m = re.fullmatch(rf"/api/{lib}/items/(\w+)/fulltext", path)
        if m:
            return self._resp(404, text="Not found")
        m = re.fullmatch(rf"/api/{lib}/items/(\w+)/file/view/url", path)
        if m and m.group(1) in self.items:
            href = ((self.items[m.group(1)].get("links") or {}).get("enclosure") or {}).get("href")
            return self._resp(200, text=href) if href else self._resp(404, text="Not found")
        m = re.fullmatch(rf"/api/{lib}/items/(\w+)", path)
        if m and m.group(1) in self.items:
            item = self.items[m.group(1)]
            if params.get("format") == "bibtex":
                d = item["data"]
                cite = f"{d['creators'][0]['lastName'].lower()}_{d['title'].split()[0].lower()}_{d.get('date')}"
                return self._resp(200, text=f"\n@article{{{cite},\n\ttitle = {{{d['title']}}},\n\tyear = {{{d.get('date')}}},\n}}\n")
            return self._resp(200, item)
        return self._resp(404, text="Not found")

    def _csl(self, item: dict) -> dict:
        d = item["data"]
        return {"id": f"0/{item['key']}", "type": "article-journal", "title": d["title"],
                "author": [{"family": c.get("lastName", ""), "given": c.get("firstName", "")} for c in d["creators"]],
                "issued": {"date-parts": [[int(d.get("date") or 0)]]}}

    def _write(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Zotero-API-Key") != self.local_key:
            return self._resp(401, text="API key required")
        body = json.loads(request.content or b"null")
        self.writes.append({"method": request.method, "path": request.url.path, "body": body})
        path = request.url.path
        if request.method == "POST" and path.endswith("/items"):
            success = {}
            for i, obj in enumerate(body):
                if obj.get("key") and obj["key"] in self.items:
                    self.items[obj["key"]]["data"].update({k: v for k, v in obj.items() if k not in ("key", "version")})
                    key = obj["key"]
                else:
                    key = self._key()
                    self.version += 1
                    self.items[key] = {"key": key, "version": self.version, "data": {"key": key, **obj}}
                success[str(i)] = key
            return self._resp(200, {"success": success, "successful": {}, "unchanged": {}, "failed": {}})
        if request.method == "POST" and path.endswith("/collections"):
            success = {}
            for i, obj in enumerate(body):
                key = self._key()
                self.add_collection(key, obj["name"], obj.get("parentCollection"))
                success[str(i)] = key
            return self._resp(200, {"success": success, "successful": {}, "unchanged": {}, "failed": {}})
        if request.method == "PATCH":
            key = path.rsplit("/", 1)[-1]
            self.items[key]["data"].update(body)
            return self._resp(204, text="")
        return self._resp(400, text="unsupported")


class ScriptedModel(ChatModel):
    """LLM-Attrappe: wählt die Antwort anhand eines Schlüsselworts im Prompt."""

    provider = "fake"

    def __init__(self, rules: list[tuple[str, str]], default: str = "OK", meter=None):
        super().__init__("fake-model", meter)
        self.rules = rules
        self.default = default
        self.calls: list[str] = []

    def _stream(self, system, messages, params):
        prompt = (system or "") + "\n" + "\n".join(m.content for m in messages)
        self.calls.append(prompt)
        reply = self.default
        for needle, answer in self.rules:
            if needle in prompt:
                reply = answer(prompt) if callable(answer) else answer
                break
        for i in range(0, len(reply), 40):
            yield StreamEvent("text", text=reply[i:i + 40])
        yield StreamEvent("done", usage=Usage(10, 5, 0, 1), stop_reason="end_turn", model=self.model)
