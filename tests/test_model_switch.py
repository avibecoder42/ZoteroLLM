"""Wechsel des Embedding-Modells: Texte gelten erst als indexiert, wenn sie mit dem aktiven Modell durchsuchbar sind;
gelesene Texte werden für das neue Modell nur eingebettet (nicht neu gelesen); zurückwechseln geht sofort."""

import json

import httpx
import pytest
from conftest import HashEmbedder
from fastapi.testclient import TestClient
from test_indexing_search import build_library, run_index

from zotivity.embeddings import make_embedder
from zotivity.embeddings.ollama import OllamaEmbedder
from zotivity.settings import EmbeddingSettings

H = {"X-Zotivity": "1"}


class NamedHash(HashEmbedder):
    """Test-Embedder mit eigenem Modellnamen (eigener Embedding-Raum)."""

    def __init__(self, model):
        super().__init__()
        self.model = model


@pytest.fixture
def switch(zengine, monkeypatch):
    """switch("modell"): ab jetzt bettet die Engine mit diesem Modell ein; liefert dessen Raum."""
    def to(model):
        emb = NamedHash(model)
        monkeypatch.setattr(zengine, "embedder", lambda: emb)
        return zengine.space()
    return to


def test_switch_embeds_without_reading_again(zengine, fake_zotero, switch):
    build_library(fake_zotero)
    old = zengine.space()
    run_index(zengine)
    before = zengine.store.scope_stats(None, old)
    assert before["indexed"] == 2 and before["to_embed"] == 0 and before["chunks_missing"] == 0

    new = switch("hash-neu")
    st = zengine.store.scope_stats(None, new)
    # Gelesen, aber mit dem neuen Modell noch nicht durchsuchbar
    assert st["read"] == 2 and st["indexed"] == 0 and st["to_embed"] == 2 and st["embedded"] == 0
    assert st["chunks_missing"] == st["chunks"] > 0
    assert {a["key"] for a in zengine.store.attachments_to_embed(new, None)} == {"ATTA0001", "ATTB0001"}
    assert zengine.store.abstracts_to_embed(new, None)

    result, job = run_index(zengine)
    assert result["extracted"] == 0 and result["embedded_docs"] == 2  # nicht neu gelesen
    assert job.title.startswith("Einbetten für ") and job.title.endswith(": alle Korpora")
    assert job.counters["embedded_docs"] == 2 and job.counters["read_docs"] == 0 and job.counters["problems"] == 0
    assert job.counters["fraction"] == 1.0 and job.counters["eta"] == 0
    after = zengine.store.scope_stats(None, new)
    assert after["indexed"] == 2 and after["to_embed"] == 0 and after["embedded"] == after["chunks"]
    run = zengine.store.index_runs()[0]
    assert run["embedded_docs"] == 2 and run["indexed"] == 0 and run["model"] == zengine.embedding_label()
    assert {d["status"] for d in zengine.store.index_run(run["id"])["docs"]} == {"embedded"}
    # Der Index des bisherigen Modells bleibt vollständig
    assert zengine.store.scope_stats(None, old)["indexed"] == 2


def test_corpus_embeds_only_its_own_texts(zengine, fake_zotero, switch):
    build_library(fake_zotero)
    run_index(zengine)
    new = switch("hash-neu")
    cid = zengine.store.create_corpus("Soziale Arbeit", ["users/0:COLB0002"])
    _, job = run_index(zengine, corpus_id=cid)
    assert job.title.endswith(": Soziale Arbeit") and job.counters["embedded_docs"] == 1
    assert {a["key"] for a in zengine.store.attachments_to_embed(new, None)} == {"ATTA0001"}
    st = zengine.store.scope_stats(None, new)
    assert st["indexed"] == 1 and st["to_embed"] == 1


def test_text_in_progress_counts_as_open(zengine, fake_zotero, monkeypatch):
    """Ein gerade gelesener, noch nicht fertig eingebetteter Text ist „offen“, nicht „einzubetten“."""
    from zotivity.index.indexer import Indexer

    build_library(fake_zotero)
    seen = []
    embed_rows = Indexer._embed_rows

    def spy(self, rows, job, space=None):
        if not seen:
            seen.append(self.store.scope_stats(None, zengine.space()))
        return embed_rows(self, rows, job, space)

    monkeypatch.setattr(Indexer, "_embed_rows", spy)
    run_index(zengine)
    assert seen[0]["to_embed"] == 0 and seen[0]["pending"] == 2 and seen[0]["indexed"] == 0
    assert zengine.store.busy is None


def test_mixed_run_reads_new_and_embeds_old(zengine, fake_zotero, switch):
    build_library(fake_zotero)
    run_index(zengine)
    switch("hash-neu")
    fake_zotero.add_item("ITEMC001", "Neuer Text", "Neu", "2025", collections=["COLB0002"])
    fake_zotero.add_pdf("ATTC0001", "ITEMC001", ["Ein neuer Text über Beratung in der Sozialen Arbeit. " * 40])
    result, job = run_index(zengine)
    assert result["extracted"] == 1 and result["embedded_docs"] == 2
    assert job.counters["to_read"] == 1 and job.counters["to_embed"] == 2
    assert not job.title.startswith("Einbetten")  # gemischter Lauf bleibt eine Indexierung


def test_api_reports_model_and_texts_to_embed(zengine, fake_zotero, switch, monkeypatch):
    build_library(fake_zotero)
    run_index(zengine)
    switch("hash-neu")
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        o = c.get("/api/index/overview").json()
        assert o["stats"]["indexed"] == 0 and o["stats"]["to_embed"] == 2 and o["stats"]["read"] == 2
        assert o["model"]["label"] == zengine.embedding_label() and o["model"]["ok"]
        assert o["embed_estimate"] is None or o["embed_estimate"] >= 0
        cid = zengine.store.corpora()[0]["id"]
        d = c.get(f"/api/corpora/{cid}/documents").json()
        assert not d["indexed"] and len(d["to_embed"]) == 2 and all(e["missing"] > 0 for e in d["to_embed"])
        assert d["model"] == zengine.embedding_label()
        index_step = next(s for s in c.get("/api/setup").json()["steps"] if s["id"] == "index")
        assert not index_step["done"] and "2 Texte einzubetten" in index_step["detail"]
        assert o["model"]["space"] == zengine.space()
        # Nur die fehlenden Abschnitte der einzubettenden Texte und Abstracts – hier: alle Abschnitte
        assert o["stats"]["to_embed_chunks"] == o["stats"]["chunks_missing"] > 0
        st = c.get("/api/status").json()["index"]["coverage"]
        assert st["indexed"] == 0 and st["to_embed"] == 2


def test_texts_waiting_for_reread_stay_searchable(zengine, fake_zotero, monkeypatch):
    """Neu zu lesende Texte (z. B. für Seitenzahlen) sind „zu aktualisieren“ und durchsuchbar, nicht „offen“."""
    build_library(fake_zotero)
    run_index(zengine)
    space = zengine.space()
    zengine.store.mark_pending("users/0", ["ATTA0001", "ATTB0001"])
    st = zengine.store.scope_stats(None, space)
    assert st["refresh"] == 2 and st["pending"] == 0 and st["indexed"] == 0 and st["to_embed_chunks"] == 0
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        step = next(s for s in c.get("/api/setup").json()["steps"] if s["id"] == "index")
        assert step["done"] and "2 von 2 Dokumenten" in step["detail"] and "2 Texte zu aktualisieren" in step["detail"]
        d = c.get(f"/api/corpora/{zengine.store.corpora()[0]['id']}/documents").json()
        assert len(d["refresh"]) == 2 and not d["pending"]
    result, _ = run_index(zengine)
    assert result["extracted"] == 2
    assert zengine.store.scope_stats(None, space)["indexed"] == 2


def test_embed_only_reads_nothing(zengine, fake_zotero, switch):
    build_library(fake_zotero)
    run_index(zengine)
    zengine.store.mark_pending("users/0", ["ATTB0001"])  # wartet auf erneutes Lesen
    new = switch("hash-neu")
    st = zengine.store.scope_stats(None, new)
    # ATTB0001 hat im neuen Raum keine Vektoren: nicht durchsuchbar, also „offen“ (das nächste Indexieren liest es)
    assert st["to_embed"] == 1 and st["pending"] == 1 and st["refresh"] == 0
    missing_a = zengine.store.missing_by_attachment(new)[("users/0", "ATTA0001")]
    assert st["to_embed_chunks"] == missing_a + len(zengine.store.abstracts_to_embed(new, None))
    result, job = run_index(zengine, sync=False, embed_only=True)
    assert result["extracted"] == 0 and result["embedded_docs"] == 1 and job.title.startswith("Einbetten für ")
    st = zengine.store.scope_stats(None, new)
    assert st["indexed"] == 1 and st["pending"] == 1 and st["to_embed"] == 0 and st["to_embed_chunks"] == 0


def test_prefix_overrides_for_catalog_models(zengine, monkeypatch):
    from zotivity.embeddings import model_catalog

    default = model_catalog.catalog_runtime("bge-m3")
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    zengine.settings_store.update({"embedding": {"provider": "ollama", "model": "bge-m3"}})
    with TestClient(create_app(zengine)) as c:
        r = c.put("/api/embedding/local/bge-m3/prefixes", json={"query_prefix": "frage: ", "document_prefix": ""},
                  headers=H)
        assert r.status_code == 200 and not r.json()["active"]
        assert model_catalog.get("bge-m3").runtime.query_prefix == "frage: "
        assert model_catalog.prefix_overrides() == {"bge-m3": {"query_prefix": "frage: "}}
        # Aktives Modell mit fester Einstellung: die neuen Präfixe gelten, die Einstellung weicht
        zengine.settings_store.update({"embedding": {"provider": "builtin", "model": "bge-m3", "query_prefix": "alt"}})
        r = c.put("/api/embedding/local/bge-m3/prefixes", json={"query_prefix": "neu: ", "document_prefix": "t: "},
                  headers=H)
        assert r.json()["active"] and zengine.settings.embedding.query_prefix is None
        assert c.delete("/api/embedding/local/bge-m3/prefixes", headers=H).status_code == 200
        assert model_catalog.get("bge-m3").runtime == default and model_catalog.prefix_overrides() == {}
        assert c.put("/api/embedding/local/gibt-es-nicht/prefixes", json={}, headers=H).status_code == 404


@pytest.mark.parametrize("prefixes", [None, "eigen"])
def test_activate_saved_space(zengine, monkeypatch, prefixes):
    """„Verwenden“ bei einem gespeicherten Index stellt genau das Modell (mit seinen Präfixen) wieder ein."""
    custom = {"query_prefix": "frage: ", "document_prefix": "text: "} if prefixes else {}
    emb = make_embedder(EmbeddingSettings(provider="ollama", model="nomic-embed-text", **custom))
    emb._dim = 768
    zengine.store.ensure_space(emb.space_id, "ollama", "nomic-embed-text", 768, emb.space_params)
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        assert c.post("/api/embedding/spaces/activate", json={"space": "gibt:es:nicht"}, headers=H).status_code == 404
        r = c.post("/api/embedding/spaces/activate", json={"space": emb.space_id}, headers=H)
        assert r.status_code == 200
    cfg = zengine.settings.embedding
    assert cfg.provider == "ollama" and cfg.model == "nomic-embed-text" and cfg.dimensions is None
    if prefixes:
        assert (cfg.query_prefix, cfg.document_prefix) == ("frage: ", "text: ")
    else:  # Standard-Präfixe des Modells bleiben „automatisch“
        assert cfg.query_prefix is None and cfg.document_prefix is None
    check = make_embedder(cfg)
    check._dim = 768
    assert check.space_id == emb.space_id


def test_ollama_lists_only_embedding_models():
    caps = {"bge-m3:latest": ["embedding"], "gemma3:4b": ["completion", "vision"], "alt-embed:latest": None,
            "llama3:8b": None}

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in [*caps, "kaputt:1b"]]})
        name = json.loads(request.content)["model"]
        if name == "kaputt:1b":
            return httpx.Response(500, text="kaputt")
        body = {} if caps[name] is None else {"capabilities": caps[name]}
        return httpx.Response(200, json=body)

    emb = OllamaEmbedder(EmbeddingSettings(provider="ollama", model="bge-m3"))
    emb._http = httpx.Client(transport=httpx.MockTransport(handler))
    assert emb.list_models() == ["alt-embed:latest", "bge-m3:latest"]
