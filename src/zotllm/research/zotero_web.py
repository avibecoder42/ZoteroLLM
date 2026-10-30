"""ZoteroPort über die Zotero-Web-API (api.zotero.org) – für persönliche und Gruppenbibliotheken.

ZotLLM hat nur einen Client für die lokale API; diesen Adapter bringt das Paket deshalb selbst mit. Den Schlüssel
liefert der KeyStore (``zotero-web``), die User-ID die Konfiguration oder ``/keys/current``.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

from .errors import ResearchError, SourceError
from .http import Http
from .ports import KEY_ZOTERO_WEB, MY_LIBRARY, KeyStore

API = "https://api.zotero.org"
PAGE = 100
WRITE_BATCH = 50


class ZoteroWebPort:
    backend = "web"

    def __init__(self, http: Http, keys: KeyStore, user_id: str | None = None):
        self.http = http
        self.keys = keys
        self.user_id = str(user_id or "").strip() or None
        self._key_info: dict | None = None

    # -- Grundlagen -------------------------------------------------------------------------------
    def _key(self) -> str:
        key = self.keys.get(KEY_ZOTERO_WEB)
        if not key:
            raise ResearchError("Kein Schlüssel für die Zotero-Web-API eingerichtet (config.ini → [zotero] api_key).",
                                "zotero_config")
        return key

    def _headers(self, write: bool = False) -> dict:
        h = {"Zotero-API-Key": self._key(), "Zotero-API-Version": "3"}
        if write:
            h["Zotero-Write-Token"] = secrets.token_hex(16)
        return h

    def key_info(self) -> dict:
        if self._key_info is None:
            self._key_info = self.http.get_json(f"{API}/keys/current", headers=self._headers())
            if not self.user_id and self._key_info.get("userID"):
                self.user_id = str(self._key_info["userID"])
        return self._key_info

    def _lib(self, lib: str) -> str:
        if lib in (MY_LIBRARY, "user", "users/me"):
            if not self.user_id:
                self.key_info()
            return f"users/{self.user_id}"
        return lib

    def _get_all(self, path: str, **params) -> Iterator[dict]:
        start = 0
        while True:
            r = self.http.request("GET", f"{API}/{path}", headers=self._headers(),
                                  params={**params, "limit": PAGE, "start": start})
            batch = r.json()
            yield from batch
            start += len(batch)
            if not batch or start >= int(r.headers.get("Total-Results", start)):
                return

    def _post(self, lib: str, kind: str, objects: list[dict]) -> list[dict]:
        out = []
        for i in range(0, len(objects), WRITE_BATCH):
            batch = objects[i:i + WRITE_BATCH]
            res = self.http.request("POST", f"{API}/{self._lib(lib)}/{kind}", headers=self._headers(write=True),
                                    json=batch).json()
            success = res.get("success") or {}
            unchanged = res.get("unchanged") or {}
            failed = res.get("failed") or {}
            for j in range(len(batch)):
                s = str(j)
                if s in success:
                    out.append({"key": success[s]})
                elif s in unchanged:
                    out.append({"key": unchanged[s], "unchanged": True})
                else:
                    err = failed.get(s) or {}
                    out.append({"key": None, "error": err.get("message") or str(err) or "unbekannter Fehler"})
        return out

    # -- ZoteroPort -------------------------------------------------------------------------------
    def status(self) -> dict:
        if not self.keys.get(KEY_ZOTERO_WEB):
            return {"ok": False, "backend": "web", "message": "Kein Zotero-API-Schlüssel eingerichtet."}
        try:
            info = self.key_info()
        except (SourceError, ResearchError) as e:
            return {"ok": False, "backend": "web", "message": str(e)}
        access = info.get("access") or {}
        return {"ok": True, "backend": "web", "user_id": self.user_id, "username": info.get("username", ""),
                "write": bool((access.get("user") or {}).get("write")), "groups": access.get("groups") or {},
                "message": f"Zotero-Web-API: {info.get('username', '')} ({self.user_id})"}

    def can_write(self, lib: str = MY_LIBRARY) -> bool:
        try:
            access = self.key_info().get("access") or {}
        except (SourceError, ResearchError):
            return False
        if lib == MY_LIBRARY or lib.startswith("users/"):
            return bool((access.get("user") or {}).get("write"))
        groups = access.get("groups") or {}
        gid = lib.split("/", 1)[-1]
        g = groups.get(gid) or groups.get("all") or {}
        return bool(g.get("write"))

    def libraries(self) -> list[dict]:
        libs = [{"lib": MY_LIBRARY, "name": "Meine Bibliothek"}]
        self._lib(MY_LIBRARY)
        for g in self._get_all(f"users/{self.user_id}/groups"):
            libs.append({"lib": f"groups/{g['id']}", "name": (g.get("data") or {}).get("name") or str(g["id"])})
        return libs

    def collections(self, lib: str) -> list[dict]:
        return [{"key": c["key"], "name": c["data"]["name"], "parent": c["data"].get("parentCollection") or None}
                for c in self._get_all(f"{self._lib(lib)}/collections")]

    def iter_items(self, lib: str) -> Iterator[dict]:
        for it in self._get_all(f"{self._lib(lib)}/items/top", itemType="-attachment"):
            if (it.get("data") or {}).get("itemType") != "note":
                yield it

    def create_collection(self, lib: str, name: str, parent: str | None = None) -> str:
        obj = {"name": name, **({"parentCollection": parent} if parent else {})}
        res = self._post(lib, "collections", [obj])[0]
        if not res.get("key"):
            raise SourceError(f"Sammlung „{name}“ konnte nicht angelegt werden: {res.get('error')}")
        return res["key"]

    def create_items(self, lib: str, items: list[dict]) -> list[dict]:
        return self._post(lib, "items", items)

    def add_to_collection(self, lib: str, collection_key: str, item_keys: list[str]) -> int:
        patches = []
        for i in range(0, len(item_keys), WRITE_BATCH):
            batch = item_keys[i:i + WRITE_BATCH]
            items = self.http.get_json(f"{API}/{self._lib(lib)}/items", headers=self._headers(),
                                       params={"itemKey": ",".join(batch), "limit": WRITE_BATCH})
            for it in items:
                cols = list(it["data"].get("collections") or [])
                if collection_key not in cols:
                    patches.append({"key": it["key"], "version": it["version"], "collections": cols + [collection_key]})
        if not patches:
            return 0
        return sum(1 for r in self._post(lib, "items", patches) if r.get("key"))
