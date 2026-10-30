"""Zotero-Adapter gegen simulierte APIs: Web-API (zotero.org, ZoteroWebPort des Pakets) und lokale API von Zotero 10
(ZoteroClientPort um ZotLLMs ZoteroClient). Geschrieben wird nur in Attrappen."""

from __future__ import annotations

import threading

import httpx
import pytest
from research_fakes import MemoryKeyStore, json_body

from zotllm import winfocus
from zotllm.keystore import get_store
from zotllm.research.errors import ResearchError, SourceError, ZoteroWriteRefused
from zotllm.research.http import Http
from zotllm.research.zotero_web import ZoteroWebPort
from zotllm.research_adapters import ZoteroClientPort
from zotllm.zotero import ZoteroClient


@pytest.fixture(autouse=True)
def no_window_watch(monkeypatch):
    """Die Freigabe holt sonst den Zotero-Dialog nach vorne (Fensterbeobachtung unter Windows)."""
    monkeypatch.setattr(winfocus, "start_dialog_watch", threading.Event)


class WebSim:
    def __init__(self):
        self.requests = []
        self.items = [{"key": f"K{i}", "version": 1, "data": {"itemType": "journalArticle", "title": f"T{i}", "collections": []}}
                      for i in range(150)] + [{"key": "N1", "version": 1, "data": {"itemType": "note"}}]

    def __call__(self, req: httpx.Request):
        self.requests.append(req)
        assert req.headers["Zotero-API-Key"] == "SECRET"
        path, params = req.url.path, dict(req.url.params)
        if path == "/keys/current":
            return httpx.Response(200, json={"userID": 6315688, "username": "solal", "access": {
                "user": {"library": True, "write": True}, "groups": {"4755508": {"library": True, "write": True}}}})
        if path == "/users/6315688/groups":
            return httpx.Response(200, json=[{"id": 4755508, "data": {"name": "Cyberaggression Cyberbelaestigung Cyberausgrenzung"}}],
                                  headers={"Total-Results": "1"})
        if path.endswith("/collections") and req.method == "GET":
            return httpx.Response(200, json=[{"key": "A", "data": {"name": "Rollen", "parentCollection": False}}], headers={"Total-Results": "1"})
        if path.endswith("/items/top"):
            start, limit = int(params["start"]), int(params["limit"])
            assert params["itemType"] == "-attachment"
            return httpx.Response(200, json=self.items[start:start + limit], headers={"Total-Results": str(len(self.items))})
        if path.endswith("/items") and req.method == "GET":
            keys = params["itemKey"].split(",")
            return httpx.Response(200, json=[it for it in self.items if it["key"] in keys])
        if req.method == "POST":
            assert len(req.headers["Zotero-Write-Token"]) == 32
            body = json_body(req)
            ok = {str(i): f"NEW{i}" for i, o in enumerate(body) if o.get("title") != "bad"}
            failed = {str(i): {"code": 400, "message": "kaputt"} for i, o in enumerate(body) if o.get("title") == "bad"}
            return httpx.Response(200, json={"success": ok, "successful": {}, "unchanged": {}, "failed": failed})
        return httpx.Response(404)


@pytest.fixture
def web():
    sim = WebSim()
    port = ZoteroWebPort(Http(transport=httpx.MockTransport(sim), sleep=lambda s: None), MemoryKeyStore(zotero_web="SECRET"))
    return port, sim


def test_web_read(web):
    port, sim = web
    st = port.status()
    assert st["ok"] and st["user_id"] == "6315688" and st["write"]
    assert port.libraries() == [{"lib": "users/0", "name": "Meine Bibliothek"},
                                {"lib": "groups/4755508", "name": "Cyberaggression Cyberbelaestigung Cyberausgrenzung"}]
    assert port.can_write("groups/4755508") and not port.can_write("groups/1")
    items = list(port.iter_items("groups/4755508"))
    assert len(items) == 150  # zwei Seiten, Notiz ausgelassen
    assert any(r.url.path == "/groups/4755508/items/top" for r in sim.requests)
    assert port.collections("users/0") == [{"key": "A", "name": "Rollen", "parent": None}]
    assert any(r.url.path == "/users/6315688/collections" for r in sim.requests)


def test_web_write(web):
    port, sim = web
    res = port.create_items("groups/4755508", [{"title": "ok"}, {"title": "bad"}])
    assert res == [{"key": "NEW0"}, {"key": None, "error": "kaputt"}]
    assert port.create_collection("groups/4755508", "neu", "A") == "NEW0"
    assert port.add_to_collection("users/0", "A", ["K1", "K2"]) == 2
    patch = json_body(sim.requests[-1])
    assert patch[0] == {"key": "K1", "version": 1, "collections": ["A"]}


def test_web_without_key():
    port = ZoteroWebPort(Http(transport=httpx.MockTransport(lambda r: httpx.Response(500)), sleep=lambda s: None), MemoryKeyStore())
    assert port.status()["ok"] is False
    with pytest.raises(ResearchError):
        port.collections("users/0")


def test_local_authorize_and_write():
    seen = []

    def handle(req: httpx.Request):
        seen.append(req)
        path = req.url.path
        h = {"Zotero-Server-ID": "SID"}
        if path == "/connector/ping":
            return httpx.Response(200, headers={"X-Zotero-Version": "10.0"})
        if path == "/api/":
            return httpx.Response(200, headers=h)
        if path == "/api/local/authorize":
            assert req.headers["Zotero-Server-ID"] == "SID"
            return httpx.Response(200, json={"key": "LOCALKEY", "remember": False}, headers=h)
        if path == "/api/users/0/groups":
            return httpx.Response(200, json=[{"id": 4755508, "data": {"name": "Gruppe"}}], headers=h)
        if path == "/api/groups/4755508/items" and req.method == "POST":
            assert req.headers["Zotero-API-Key"] == "LOCALKEY" and req.headers["Zotero-Server-ID"] == "SID"
            return httpx.Response(200, json={"success": {"0": "AAA"}}, headers=h)
        return httpx.Response(404, headers=h)

    client = ZoteroClient(transport=httpx.MockTransport(handle), keystore=get_store())
    port = ZoteroClientPort(lambda: client)
    st = port.status()
    assert st["ok"] and st["version"] == "10.0" and not st["write"] and st["backend"] == "local"
    assert port.libraries()[1] == {"lib": "groups/4755508", "name": "Gruppe"}
    with pytest.raises(ZoteroWriteRefused) as e:
        port.create_items("groups/4755508", [{"title": "x"}])
    assert e.value.kind == "zotero_auth"
    assert port.authorize() is True and port.can_write("groups/4755508")
    assert port.status()["write"] and port.status()["message"] == "Zotero 10.0 (lokal)"
    assert port.create_items("groups/4755508", [{"title": "x"}]) == [{"key": "AAA"}]


def test_local_not_running():
    def handle(req):
        raise httpx.ConnectError("refused", request=req)

    port = ZoteroClientPort(lambda: ZoteroClient(transport=httpx.MockTransport(handle), keystore=get_store()))
    st = port.status()
    assert st == {**st, "ok": False, "message": "Zotero läuft nicht."}
    assert port.can_write("users/0") is False
    with pytest.raises(SourceError):  # die Fachlogik fängt ResearchError (z. B. KI-Vorschlag ohne Zotero)
        port.collections("users/0")


def test_local_port_with_zotllm_client(zengine, fake_zotero):
    """Lesen und Schreiben über ZotLLMs Client gegen die simulierte lokale API (wie ZotLLM sie testet)."""
    fake_zotero.add_collection("C1", "Rollen")
    fake_zotero.add_collection("C2", "neu", "C1")
    fake_zotero.add_item("I1", "Teasing among adolescents", collections=["C1"])
    fake_zotero.add_note("N1", None)
    port = ZoteroClientPort(lambda: zengine.zotero())
    assert sorted((c["key"], c["name"], c["parent"]) for c in port.collections("users/0")) == [
        ("C1", "Rollen", None), ("C2", "neu", "C1")]
    assert [it["key"] for it in port.iter_items("users/0")] == ["I1"]  # ohne Notizen und Anhänge
    assert port.libraries() == [{"lib": "users/0", "name": "Meine Bibliothek"}]
    assert port.authorize() and port.can_write("users/0")
    key = port.create_collection("users/0", "Ostracism", "C1")
    assert fake_zotero.collections[key]["data"]["parentCollection"] == "C1"
    new = port.create_items("users/0", [{"itemType": "journalArticle", "title": "Neu", "collections": [key]}])
    assert new[0]["key"] in fake_zotero.items
    assert port.add_to_collection("users/0", key, ["I1"]) == 1
    assert key in fake_zotero.items["I1"]["data"]["collections"]
