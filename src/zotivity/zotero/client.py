"""Client für die lokale Zotero-API (Zotero 7+, Schreibzugriff ab Zotero 10).

Grundsätze (siehe Konzept):
- Nur über die API arbeiten, nie zotero.sqlite direkt lesen (Zotero 10 nutzt WAL,
  direkte Leser können unvollständige Daten sehen).
- Lesen braucht keine Anmeldung. Schreiben braucht einen lokalen API-Schlüssel,
  den Zotero nach einer Rückfrage ("Erlauben"/"Immer erlauben") ausgibt, sowie die
  Zotero-Server-ID im Header.
"""

from __future__ import annotations

import logging
import secrets as _stdsecrets
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from zotivity import APP_NAME
from zotivity.keystore import SecretStore, get_store

log = logging.getLogger(__name__)

API_VERSION = "3"
WRITE_BATCH = 50  # MAX_WRITE_OBJECTS in Zotero


class ZoteroError(RuntimeError):
    pass


class ZoteroUnavailable(ZoteroError):
    """Zotero läuft nicht oder die lokale API ist deaktiviert."""


class ZoteroAuthRequired(ZoteroError):
    """Schreibzugriff wurde (noch) nicht freigegeben."""


class PluginMissing(ZoteroError):
    """Das Zotivity-Plugin fehlt in Zotero oder ist zu alt für die gewünschte Funktion."""


def file_url_to_path(url: str) -> Path | None:
    if not url or not url.startswith("file:"):
        return None
    try:
        return Path.from_uri(url)  # Python 3.13+
    except (AttributeError, ValueError):
        from urllib.parse import unquote, urlparse
        from urllib.request import url2pathname

        parsed = urlparse(url)
        return Path(url2pathname(unquote(parsed.path)))


class ZoteroClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:23119",
        keystore: SecretStore | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.keystore = keystore or get_store()
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=3.0),
            headers={"Zotero-API-Version": API_VERSION, "User-Agent": f"{APP_NAME}"},
            trust_env=False,  # lokale Verbindung nie über Proxy
            transport=transport,
        )
        self._server_id: str | None = None
        self._lock = threading.Lock()
        self._unavailable_at = 0.0  # letzter Fehlschlag (monotonic), siehe is_available

    def close(self) -> None:
        self._http.close()

    # -- Grundfunktionen ---------------------------------------------------------
    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = self._http.request(method, url, **kw)
        except httpx.TransportError as e:
            raise ZoteroUnavailable("Zotero ist nicht erreichbar. Läuft Zotero?") from e
        sid = r.headers.get("Zotero-Server-ID")
        if sid:
            self._server_id = sid
        if r.status_code == 403 and "not enabled" in r.text:
            raise ZoteroUnavailable(
                "Die lokale API ist in Zotero deaktiviert. Zotero → Einstellungen → Erweitert → "
                "„Anderen Anwendungen auf diesem Computer erlauben, mit Zotero zu kommunizieren“ aktivieren."
            )
        return r

    def _get_json(self, url: str, params: dict | None = None) -> Any:
        r = self._request("GET", url, params=params)
        if r.status_code == 404:
            raise ZoteroError(f"Nicht gefunden: {url}")
        if r.status_code >= 400:
            raise ZoteroError(f"Zotero-Fehler {r.status_code}: {r.text[:300]}")
        return r.json()

    def status(self) -> dict:
        """Prüft Erreichbarkeit und ob die lokale API aktiv ist."""
        out = {"running": False, "local_api": False, "server_id": None, "version": None, "message": ""}
        try:
            r = self._http.get("/connector/ping")
            out["running"] = r.status_code == 200
            out["version"] = r.headers.get("X-Zotero-Version")
        except httpx.TransportError:
            out["message"] = "Zotero läuft nicht."
            self._unavailable_at = time.monotonic()
            return out
        try:
            self._request("GET", "/api/")
            out["local_api"] = True
            out["server_id"] = self._server_id
            self._unavailable_at = 0.0
        except ZoteroUnavailable as e:
            out["message"] = str(e)
            self._unavailable_at = time.monotonic()
        return out

    UNAVAILABLE_TTL = 30.0

    def is_available(self, fresh: bool = False) -> bool:
        """Lokale API erreichbar? Ein Fehlschlag gilt UNAVAILABLE_TTL Sekunden: Ist Zotero geschlossen, kostet unter
        Windows jeder Verbindungsversuch rund 2 s – Kopieren oder Exportieren warten dann nicht jedes Mal darauf.
        Statusabfrage (status) und Hintergrundplaner (fresh) prüfen immer neu; ein gestartetes Zotero fällt so
        spätestens beim nächsten Abruf auf."""
        if not fresh and self._unavailable_at and time.monotonic() - self._unavailable_at < self.UNAVAILABLE_TTL:
            return False
        try:
            ok = self._request("GET", "/api/").status_code == 200
        except ZoteroUnavailable:
            ok = False
        self._unavailable_at = 0.0 if ok else time.monotonic()
        return ok

    @property
    def server_id(self) -> str:
        if not self._server_id:
            self._request("GET", "/api/")
        if not self._server_id:
            raise ZoteroUnavailable("Zotero-Server-ID unbekannt.")
        return self._server_id

    def item_uris(self, refs: list[str]) -> dict[str, str]:
        """Zotero-URIs der Einträge („lib:KEY“), wie sie Word-Belege speichern – über das Zotivity-Plugin.
        Ohne Plugin (oder bei älterer Version) ein leeres Ergebnis."""
        # Plugins früherer Versionen (ZotLLM, ZoteroLLM) bieten dieselbe Schnittstelle unter dem alten Pfad
        for endpoint in ("/zotivity/uris", "/zotllm/uris", "/zoterollm/uris"):
            try:
                r = self._request("POST", endpoint, json={"items": list(refs)},
                                  headers={"Zotero-Server-ID": self.server_id})
            except ZoteroError:
                return {}
            if r.status_code != 404:
                break
        if r.status_code != 200:
            return {}
        try:
            return {k: v for k, v in (r.json().get("uris") or {}).items() if v}
        except ValueError:
            return {}

    def schema(self) -> dict:
        """Zotero-Schema: Eintragsarten mit Feldern und Rollen, ihre Namen in allen Sprachen, Zuordnung zu CSL."""
        return self._get_json("/api/schema")

    def install_style(self, xml: str) -> None:
        """Eigenen Zitierstil über das Zotivity-Plugin installieren (Zotero.Styles.install: sofort in Zotero und im
        Word-Plugin verfügbar). Ohne Plugin ab 1.1.0: PluginMissing."""
        r = self._request("POST", "/zotivity/styles/install", json={"style": xml},
                          headers={"Zotero-Server-ID": self.server_id, "X-Zotivity": "1"})
        if r.status_code == 404:
            raise PluginMissing("Für das direkte Installieren braucht es das Zotivity-Plugin ab Version 1.1.0.")
        if r.status_code >= 400:
            try:
                detail = r.json().get("error") or r.text
            except ValueError:
                detail = r.text
            raise ZoteroError(f"Zotero konnte den Stil nicht installieren: {detail[:300]}")

    # -- Lesen ---------------------------------------------------------------------
    def library_version(self, lib: str) -> int:
        return self.library_stamp(lib)[0]

    def library_stamp(self, lib: str) -> tuple[int, int]:
        """(Versionsnummer, Zahl der Einträge) einer Bibliothek – eine kleine Anfrage. Die Versionsnummer steigt bei
        jeder Änderung; Gruppen melden in Zotero 10 lokal immer 0, dort zeigt nur die Zahl der Einträge Änderungen."""
        r = self._request("GET", f"/api/{lib}/items", params={"limit": 1, "format": "keys"})
        if r.status_code >= 400:
            raise ZoteroError(f"Zotero-Fehler {r.status_code}: {r.text[:200]}")
        return int(r.headers.get("Last-Modified-Version", "0")), int(r.headers.get("Total-Results", "0") or 0)

    def groups(self) -> list[dict]:
        return self._get_json("/api/users/0/groups")

    def collections(self, lib: str) -> list[dict]:
        return self._get_json(f"/api/{lib}/collections")

    def item_keys(self, lib: str, item_type: str | None = None, collection: str | None = None,
                  exclude_types: list[str] | None = None) -> list[str]:
        """Nur Schlüssel (ohne JSON) – billig, Zotero berechnet dafür keine MD5-Summen."""
        params: dict[str, Any] = {"format": "keys"}
        types = ([item_type] if item_type else []) + [f"-{t}" for t in exclude_types or []]
        if types:
            params["itemType"] = types
        url = f"/api/{lib}/collections/{collection}/items" if collection else f"/api/{lib}/items"
        r = self._request("GET", url, params=params)
        if r.status_code >= 400:
            raise ZoteroError(f"Zotero-Fehler {r.status_code}: {r.text[:200]}")
        return [k for k in r.text.split("\n") if k.strip()]

    def count_top_items(self, lib: str) -> int | None:
        """Anzahl Einträge (ohne Anhänge/Notizen) – nur Schlüssel, daher billig."""
        r = self._request("GET", f"/api/{lib}/items/top", params={"format": "keys", "limit": 1})
        if r.status_code >= 400:
            return None
        try:
            return int(r.headers.get("Total-Results", ""))
        except ValueError:
            return None

    def iter_items(
        self,
        lib: str,
        *,
        since: int | None = None,
        item_type: str | None = None,
        top: bool = False,
        keys: list[str] | None = None,
        collection: str | None = None,
        page_size: int = 200,
    ) -> Iterator[dict]:
        """Liefert Einträge seitenweise (Anhänge berechnen MD5 – daher nicht alles auf einmal)."""
        if keys is not None:
            for i in range(0, len(keys), 50):
                batch = keys[i : i + 50]
                if not batch:
                    continue
                params: dict[str, Any] = {"itemKey": ",".join(batch)}
                if item_type:
                    params["itemType"] = item_type
                yield from self._get_json(f"/api/{lib}/items", params)
            return
        base = f"/api/{lib}/collections/{collection}/items" if collection else f"/api/{lib}/items"
        if top:
            base += "/top"
        start = 0
        while True:
            params = {"start": start, "limit": page_size, "sort": "dateModified", "direction": "asc"}
            if since:
                params["since"] = since
            if item_type:
                params["itemType"] = item_type
            page = self._get_json(base, params)
            if not page:
                break
            yield from page
            if len(page) < page_size:
                break
            start += page_size

    def item(self, lib: str, key: str) -> dict:
        return self._get_json(f"/api/{lib}/items/{key}")

    def children(self, lib: str, key: str) -> list[dict]:
        return self._get_json(f"/api/{lib}/items/{key}/children")

    def fulltext(self, lib: str, att_key: str) -> str | None:
        r = self._request("GET", f"/api/{lib}/items/{att_key}/fulltext")
        if r.status_code != 200:
            return None
        try:
            return (r.json() or {}).get("content") or None
        except ValueError:
            return None

    def file_path(self, lib: str, att_json: dict) -> Path | None:
        """Pfad zur Datei eines Anhangs (gespeichert oder verknüpft)."""
        href = ((att_json.get("links") or {}).get("enclosure") or {}).get("href")
        path = file_url_to_path(href) if href else None
        if path is None:
            r = self._request("GET", f"/api/{lib}/items/{att_json['key']}/file/view/url")
            if r.status_code == 200:
                path = file_url_to_path(r.text.strip())
        return path

    # -- Schreiben -----------------------------------------------------------------
    def _key_name(self) -> str:
        return f"zotero-local:{self.server_id}"

    def has_write_access(self) -> bool:
        # Gespeicherter Schlüssel („Entscheidung merken“) oder Schlüssel für diese Sitzung
        return bool(self.keystore.get(self._key_name()) or getattr(self, "_one_time_key", None))

    def authorize(self, timeout: float = 300.0) -> bool:
        """Fragt in Zotero nach Schreibrechten (Dialog). Gibt True bei Erfolg zurück."""
        # Zotero 10 verlangt die Server-ID bei allen POST-Anfragen, auch bei der Autorisierung
        r = self._request(
            "POST",
            "/api/local/authorize",
            json={"appName": APP_NAME},
            headers={"Zotero-Server-ID": self.server_id},
            timeout=httpx.Timeout(timeout, connect=3.0),
        )
        if r.status_code == 412:
            self._server_id = None
            raise ZoteroError("Zotero-Instanz hat gewechselt – bitte erneut versuchen.")
        if r.status_code == 403:
            return False
        if r.status_code == 429:
            raise ZoteroError("Zu viele Autorisierungsanfragen – bitte später erneut versuchen.")
        if r.status_code != 200:
            raise ZoteroError(f"Autorisierung fehlgeschlagen ({r.status_code}): {r.text[:200]}")
        data = r.json()
        if data.get("remember"):
            self.keystore.set(self._key_name(), data["key"])
        else:
            # Einmal-Schlüssel nur im Speicher halten
            self._one_time_key = data["key"]
        return True

    def revoke_local(self) -> None:
        self.keystore.delete(self._key_name())
        self._one_time_key = None

    def _write(self, method: str, url: str, **kw) -> httpx.Response:
        key = self.keystore.get(self._key_name()) or getattr(self, "_one_time_key", None)
        if not key:
            raise ZoteroAuthRequired("Schreibzugriff auf Zotero ist noch nicht freigegeben.")
        headers = kw.pop("headers", {}) or {}
        headers.update(
            {
                "Zotero-API-Key": key,
                "Zotero-Server-ID": self.server_id,
                "Zotero-Write-Token": _stdsecrets.token_hex(16),
            }
        )
        r = self._request(method, url, headers=headers, **kw)
        if r.status_code in (401, 403):
            self.keystore.delete(self._key_name())
            self._one_time_key = None
            raise ZoteroAuthRequired("Zotero hat den Schlüssel abgelehnt – bitte erneut freigeben.")
        if r.status_code >= 400:
            raise ZoteroError(f"Zotero-Schreibfehler {r.status_code}: {r.text[:300]}")
        return r

    def _post_objects(self, lib: str, kind: str, objects: list[dict]) -> list[dict]:
        """POST in Stapeln; liefert je Objekt {'key':..., 'error':...}."""
        results: list[dict] = []
        for i in range(0, len(objects), WRITE_BATCH):
            batch = objects[i : i + WRITE_BATCH]
            r = self._write("POST", f"/api/{lib}/{kind}", json=batch)
            data = r.json()
            success = data.get("success", {}) or {}
            unchanged = data.get("unchanged", {}) or {}
            failed = data.get("failed", {}) or {}
            for j in range(len(batch)):
                s = str(j)
                if s in success:
                    results.append({"key": success[s]})
                elif s in unchanged:
                    results.append({"key": unchanged[s], "unchanged": True})
                else:
                    err = failed.get(s, {})
                    results.append({"key": None, "error": err.get("message") or str(err)})
        return results

    def create_items(self, lib: str, items: list[dict]) -> list[dict]:
        """Neue Einträge (JSON der Zotero-API) anlegen; je Eintrag {'key': …} oder {'key': None, 'error': …}."""
        return self._post_objects(lib, "items", items)

    def create_note(self, lib: str, parent_key: str | None, html: str, tags: list[str] | None = None) -> str:
        obj: dict[str, Any] = {"itemType": "note", "note": html, "tags": [{"tag": t} for t in (tags or [])]}
        if parent_key:
            obj["parentItem"] = parent_key
        res = self._post_objects(lib, "items", [obj])[0]
        if not res.get("key"):
            raise ZoteroError(f"Notiz konnte nicht angelegt werden: {res.get('error')}")
        return res["key"]

    def update_note(self, lib: str, note_key: str, html: str) -> None:
        current = self.item(lib, note_key)
        self._write(
            "PATCH",
            f"/api/{lib}/items/{note_key}",
            json={"note": html},
            headers={"If-Unmodified-Since-Version": str(current["version"])},
        )

    def create_collection(self, lib: str, name: str, parent_key: str | None = None) -> str:
        obj: dict[str, Any] = {"name": name}
        if parent_key:
            obj["parentCollection"] = parent_key
        res = self._post_objects(lib, "collections", [obj])[0]
        if not res.get("key"):
            raise ZoteroError(f"Sammlung konnte nicht angelegt werden: {res.get('error')}")
        return res["key"]

    def add_to_collection(self, lib: str, collection_key: str, item_keys: list[str]) -> int:
        """Fügt Einträge einer Sammlung hinzu (bestehende Zuordnungen bleiben erhalten)."""
        items = list(self.iter_items(lib, keys=item_keys))
        patches = []
        for it in items:
            cols = list(it["data"].get("collections", []))
            if collection_key not in cols:
                patches.append({"key": it["key"], "version": it["version"], "collections": cols + [collection_key]})
        if not patches:
            return 0
        res = self._post_objects(lib, "items", patches)
        return sum(1 for r in res if r.get("key"))

    def set_aside(self, lib: str, item_key: str, collection_keys: list[str], tag: str) -> None:
        """Eintrag aus diesen Sammlungen nehmen und mit einem Schlagwort versehen. Gelöscht wird nichts."""
        current = self.item(lib, item_key)
        data = current["data"]
        tags = list(data.get("tags", []))
        if not any(t.get("tag") == tag for t in tags):
            tags.append({"tag": tag})
        res = self._post_objects(lib, "items", [{"key": item_key, "version": current["version"], "tags": tags,
                                                 "collections": [c for c in data.get("collections", []) if c not in collection_keys]}])
        if not res[0].get("key"):
            raise ZoteroError(f"Eintrag konnte nicht geändert werden: {res[0].get('error')}")


def zotero_select_url(lib: str, item_key: str, collection_key: str | None = None) -> str:
    """Eintrag in Zotero auswählen – in der Bibliothek oder in einer bestimmten Sammlung."""
    if collection_key:
        return f"zotero://select/{_lib_path(lib)}/collections/{quote(collection_key)}/items/{quote(item_key)}"
    return f"zotero://select/{_lib_path(lib)}/items/{quote(item_key)}"


# Dateitypen, die Zotero im eigenen Reader öffnet (an einer Seite); Word & Co. öffnet es extern ohne Seitensprung
READER_TYPES = ("application/pdf", "application/epub+zip", "text/html")


def opens_in_reader(content_type: str | None) -> bool:
    """Lässt sich der Anhang mit zotero://open-pdf öffnen? Unbekannter Typ (ältere Daten): wie bisher ja."""
    return not content_type or content_type in READER_TYPES


def zotero_open_pdf_url(lib: str, att_key: str, page_index: int | None = None) -> str:
    """page_index ist 0-basiert; Zotero erwartet die 1-basierte Seitennummer im PDF."""
    url = f"zotero://open-pdf/{_lib_path(lib)}/items/{quote(att_key)}"
    if page_index is not None:
        url += f"?page={page_index + 1}"
    return url


def _lib_path(lib: str) -> str:
    # users/0 -> library ; groups/123 -> groups/123
    return "library" if lib.startswith("users/") else lib
