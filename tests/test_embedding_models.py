"""Eingebaute Embedding-Modelle: Katalog, GGUF-Kopf, Download, Laufzeit (mit Ersatz-Server), Kurztest,
Namenssuche, Indexübernahme, Vergleich, Modell je Projekt."""

import hashlib
import json
import struct
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from zotivity.embeddings import benchmark, gguf, hf_search, llama_runtime, model_catalog, model_store
from zotivity.embeddings.base import EmbeddingError
from zotivity.embeddings.model_catalog import CatalogError, ModelEntry
from zotivity.extract.chunker import Chunk
from zotivity.index import spaces
from zotivity.index.indexer import embedding_text
from zotivity.jobs import Job, JobCancelled
from zotivity.settings import EmbeddingSettings

FAKE_SERVER = Path(__file__).parent / "fake_llama_server.py"
H = {"X-Zotivity": "1"}


@pytest.fixture(autouse=True)
def fresh_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOTIVITY_HOME", str(tmp_path))
    model_catalog.invalidate()
    yield
    model_catalog.invalidate()


@pytest.fixture
def fake_runtime(monkeypatch):
    """llama-server durch tests/fake_llama_server.py ersetzen; eigene Laufzeit je Test."""
    monkeypatch.setattr(llama_runtime, "find_server", lambda: Path(sys.executable))
    orig = llama_runtime.LlamaServer.command
    monkeypatch.setattr(llama_runtime.LlamaServer, "command", lambda self: [sys.executable, str(FAKE_SERVER)] + orig(self)[1:])
    rt = llama_runtime.LlamaRuntime()
    monkeypatch.setattr(llama_runtime, "_runtime", rt)
    yield rt
    rt.stop_all()


def gguf_bytes(arch="bert", dim=16, ctx=512, pooling=2, vocab=("a", "b", "c")) -> bytes:
    def s(x):
        b = x.encode()
        return struct.pack("<Q", len(b)) + b

    kv = [("general.architecture", 8, s(arch)), ("general.name", 8, s("Testmodell")),
          ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, len(vocab)) + b"".join(s(v) for v in vocab)),
          (f"{arch}.embedding_length", 4, struct.pack("<I", dim)), (f"{arch}.context_length", 4, struct.pack("<I", ctx)),
          (f"{arch}.pooling_type", 4, struct.pack("<I", pooling)), (f"{arch}.attention.causal", 7, struct.pack("<?", False))]
    out = [b"GGUF", struct.pack("<I", 3), struct.pack("<Q", 0), struct.pack("<Q", len(kv))]
    for key, typ, val in kv:
        out += [s(key), struct.pack("<I", typ), val]
    return b"".join(out) + b"\0" * 2048


def user_entry(content: bytes, model_id="hf-test-model-q8_0", **runtime) -> ModelEntry:
    return ModelEntry.model_validate({
        "id": model_id, "name": "Testmodell", "source": {"repo": "test/model-GGUF", "revision": "abc123"},
        "file": {"name": "model-Q8_0.gguf", "quant": "Q8_0", "bytes": len(content),
                 "sha256": hashlib.sha256(content).hexdigest()},
        "runtime": {"pooling": "", "query_prefix": "query: ", "document_prefix": "", "ctx": 512, **runtime},
        "params_m": 100,
    })


def serve(content: bytes, log: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("Range")
        if log is not None:
            log.append(rng)
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            return httpx.Response(206, content=content[start:])
        return httpx.Response(200, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def install(entry: ModelEntry, content: bytes) -> dict:
    model_catalog.save_user_model(entry)
    return model_store.download(model_catalog.get(entry.id), http=serve(content))


# -- Katalog ------------------------------------------------------------------------------------------------
def test_bundled_catalog_is_complete():
    cat = model_catalog.bundled()
    ids = [m.id for m in cat.models]
    assert len(ids) == 12 and len(set(ids)) == 12
    assert [m.id for m in cat.models if m.default] == ["bge-m3"]
    groups = {g.id for g in cat.groups}
    for m in cat.models:
        assert m.group in groups, m.id
        assert len(m.file.sha256) == 64 and m.file.bytes > 10_000_000 and len(m.source.revision) == 40, m.id
        assert m.strengths.get("de") and m.strengths.get("en"), m.id
        assert m.reference.tok_per_s and m.runtime.ctx >= 512, m.id
        assert m.download_url.startswith(f"https://huggingface.co/{m.source.repo}/resolve/{m.source.revision}/")
    assert benchmark.bench_set()["queries"] and len(benchmark.bench_set()["passages"]) == 8


def test_remote_catalog_only_when_newer(tmp_path):
    data = json.loads(model_catalog.BUNDLED.read_text(encoding="utf-8"))
    newer = dict(data, version="2099.1.1")
    newer["models"] = data["models"][:2]
    src = tmp_path / "cat.json"
    src.write_text(json.dumps(newer), encoding="utf-8")
    r = model_catalog.refresh(str(src))
    assert r["updated"] and model_catalog.current().version == "2099.1.1" and len(model_catalog.all_models()) == 2
    assert model_catalog.current().models[0].origin == "remote"
    # Älterer Katalog: bleibt beim aktuellen
    src.write_text(json.dumps(dict(data, version="2000.1.1")), encoding="utf-8")
    assert not model_catalog.refresh(str(src))["updated"]
    # Ungültig oder zu neues Schema: Fehler, nichts übernommen
    src.write_text(json.dumps(dict(data, version="2100.1.1", models=[{"id": "x"}])), encoding="utf-8")
    with pytest.raises(CatalogError):
        model_catalog.refresh(str(src))
    src.write_text(json.dumps(dict(data, version="2100.1.1", schema=99)), encoding="utf-8")
    with pytest.raises(CatalogError, match="neuere Version"):
        model_catalog.refresh(str(src))
    assert model_catalog.current().version == "2099.1.1"


def test_user_models_are_kept_separately():
    content = gguf_bytes()
    e = model_catalog.save_user_model(user_entry(content))
    assert e.user and e.group == "user" and model_catalog.get(e.id).user
    with pytest.raises(CatalogError):
        model_catalog.save_user_model(model_catalog.get("bge-m3").model_copy(update={"user": True}))
    model_catalog.update_user_model(e.id, runtime={"query_prefix": "search: "})
    assert model_catalog.get(e.id).runtime.query_prefix == "search: "
    assert model_catalog.remove_user_model(e.id) and model_catalog.get(e.id) is None
    assert model_catalog.match_alias("bge-m3:latest").id == "bge-m3"
    assert model_catalog.match_alias("qwen3-embedding:0.6b").id == "qwen3-embedding-0.6b"


# -- GGUF ---------------------------------------------------------------------------------------------------
def test_gguf_header(tmp_path):
    p = tmp_path / "m.gguf"
    p.write_bytes(gguf_bytes(arch="modern-bert", dim=384, ctx=8192, pooling=2, vocab=[f"t{i}" for i in 2000 * "x"]))
    info = gguf.inspect(p)
    assert info == {"architecture": "modern-bert", "name": "Testmodell", "dim": 384, "context": 8192, "pooling": "cls",
                    "causal": False, "file_type": None}
    (tmp_path / "x.gguf").write_bytes(b"not a model")
    with pytest.raises(gguf.GGUFError):
        gguf.inspect(tmp_path / "x.gguf")


# -- Download -------------------------------------------------------------------------------------------------
def test_download_checks_sha_and_resumes():
    content = gguf_bytes() + b"\1" * (3 * 1024 * 1024)
    entry = user_entry(content)
    model_catalog.save_user_model(entry)

    class CancelAfter(Job):
        def __init__(self, n):
            super().__init__("model-download", "t")
            self.n = n

        def check(self):
            self.n -= 1
            if self.n < 0:
                raise JobCancelled()

    with pytest.raises(JobCancelled):
        model_store.download(entry, CancelAfter(1), http=serve(content))
    assert 0 < model_store.partial_bytes(entry) < len(content) and not model_store.record(entry.id)
    log = []
    rec = model_store.download(entry, http=serve(content, log))
    assert log == [f"bytes={1024 * 1024}-"]
    assert rec["gguf"]["dim"] == 16 and model_store.model_path(entry.id).read_bytes() == content
    assert model_store.partial_bytes(entry) == 0
    # Falsche Prüfsumme: verworfen
    bad = user_entry(content, model_id="hf-bad", ).model_copy(update={"file": entry.file.model_copy(update={"sha256": "0" * 64})})
    with pytest.raises(EmbeddingError, match="Prüfsumme"):
        model_store.download(bad, http=serve(content))
    assert model_store.partial_bytes(bad) == 0 and not model_store.record("hf-bad")
    assert model_store.delete(entry.id) and model_store.model_path(entry.id) is None


# -- Laufzeit und Embedder --------------------------------------------------------------------------------------
def test_builtin_embedder_with_runtime(fake_runtime):
    from zotivity.embeddings import make_embedder

    content = gguf_bytes(dim=16)
    entry = user_entry(content)
    with pytest.raises(EmbeddingError, match="Modellkatalog"):
        make_embedder(EmbeddingSettings(provider="builtin", model=entry.id))
    model_catalog.save_user_model(entry)
    with pytest.raises(EmbeddingError, match="noch nicht heruntergeladen"):
        make_embedder(EmbeddingSettings(provider="builtin", model=entry.id))
    model_store.download(model_catalog.get(entry.id), http=serve(content))
    emb = make_embedder(EmbeddingSettings(provider="builtin", model=entry.id, parallel=2))
    assert emb.dim == 16 and emb.query_prefix == "query: " and emb.pooling == "cls"  # Pooling aus der GGUF-Datei
    assert emb.space_id.startswith(f"builtin:{entry.id}:16:")
    v = emb.embed_documents(["Schulsozialarbeit und Lehrpersonen", "Gletscher und Wasser"])
    assert v.shape == (2, 16) and emb.last_tokens == 6
    assert len(fake_runtime._servers) == 1
    # Zu lange Eingabe (mehr Wörter als ctx=512): wird auf die Tokenzahl gekürzt statt abzubrechen
    long = "wort " * 900
    assert emb.embed_documents(["kurz", long]).shape == (2, 16)
    # Gleicher Server für weitere Anfragen; nach der Leerlaufzeit beendet
    emb.embed_query("frage")
    assert len(fake_runtime._servers) == 1
    fake_runtime.keep_alive = 0
    assert fake_runtime.reap(now=time.time() + 1) == 1 and not fake_runtime._servers


def test_runtime_restarts_after_crash(fake_runtime, monkeypatch):
    from zotivity.embeddings import make_embedder

    content = gguf_bytes()
    install(user_entry(content), content)
    monkeypatch.setenv("FAKE_LLAMA_CRASH_AFTER", "1")
    emb = make_embedder(EmbeddingSettings(provider="builtin", model="hf-test-model-q8_0"))
    emb.embed_query("eins")
    srv = next(iter(fake_runtime._servers.values()))
    first = srv.proc.pid
    monkeypatch.delenv("FAKE_LLAMA_CRASH_AFTER")
    assert emb.embed_query("zwei").shape == (16,)  # Absturz erkannt, neu gestartet
    assert srv.proc.pid != first


def test_missing_runtime_is_reported(monkeypatch):
    from zotivity.embeddings import make_embedder

    content = gguf_bytes()
    install(user_entry(content), content)
    monkeypatch.setattr(llama_runtime, "find_server", lambda: None)
    monkeypatch.setattr(llama_runtime, "_runtime", llama_runtime.LlamaRuntime())
    emb = make_embedder(EmbeddingSettings(provider="builtin", model="hf-test-model-q8_0"))
    with pytest.raises(EmbeddingError, match="fehlt in dieser Installation"):
        emb.embed_query("x")


def test_matryoshka_truncates_and_normalizes(fake_runtime):
    from zotivity.embeddings import make_embedder

    content = gguf_bytes()
    install(user_entry(content), content)
    emb = make_embedder(EmbeddingSettings(provider="builtin", model="hf-test-model-q8_0", dimensions=8))
    v = emb.embed_documents(["eins zwei drei"])
    assert v.shape == (1, 8) and abs(float(np.linalg.norm(v[0])) - 1) < 1e-5 and emb.space_id.split(":")[2] == "8"


# -- Zeitschätzung und Kurztest -------------------------------------------------------------------------------
def test_estimates_and_short_test(fake_runtime, monkeypatch):
    from zotivity.embeddings import make_embedder

    monkeypatch.setattr(benchmark, "cpu_score", lambda force=False: {"gflops": 200.0, "cpu": benchmark.cpu_name()})
    bge = model_catalog.get("bge-m3")
    f = benchmark.machine_factor({})
    assert f == {"factor": 0.5, "source": "cpu_test", "gflops": 200.0}
    est = benchmark.estimate(bge, f["factor"])
    assert est["source"] == "estimated" and est["tok_per_s"] == 200 and est["minutes_per_100_pages"] == 6.7
    # Gemessener Kurztest: ersetzt die Schätzung und eicht die übrigen Modelle
    content = gguf_bytes()
    install(user_entry(content), content)
    emb = make_embedder(EmbeddingSettings(provider="builtin", model="hf-test-model-q8_0"))
    res = benchmark.short_test(emb)
    assert res["tok_per_s"] > 0 and res["queries"] == 8 and res["dim"] == 16 and res["cpu"] == benchmark.cpu_name()
    model_store.set_test("hf-test-model-q8_0", res)
    assert benchmark.estimate(model_catalog.get("hf-test-model-q8_0"), 1.0, res)["source"] == "measured"
    fake = {"bge-m3": {"test": {"tok_per_s": 800, "cpu": benchmark.cpu_name()}}}
    assert benchmark.machine_factor(fake) == {"factor": 2.0, "source": "measured", "models": 1}


# -- Namenssuche ------------------------------------------------------------------------------------------------
def test_parse_hf_references():
    assert hf_search.parse_ref("https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/blob/main/x-Q8_0.gguf") == \
        {"repo": "Qwen/Qwen3-Embedding-0.6B-GGUF", "file": "x-Q8_0.gguf", "quant": None}
    assert hf_search.parse_ref("hf.co/ggml-org/bge-m3-Q8_0-GGUF:Q8_0")["quant"] == "Q8_0"
    assert hf_search.parse_ref("owner/repo")["repo"] == "owner/repo"
    assert hf_search.parse_ref("bge m3") is None and hf_search.parse_ref("bge-m3") is None
    assert hf_search.quant_of("model.Q4_K_M.gguf") == "Q4_K_M" and hf_search.quant_of("m-BF16.gguf") == "BF16"
    assert hf_search.support("bert") == "supported" and hf_search.support("qwen3", "x-Embedding") == "decoder"
    assert hf_search.support("qwen3", "Qwen3-8B") == "not_embedding" and hf_search.support("weird") == "unknown"


def test_search_and_add_user_model():
    listing = [
        {"id": "a/bge-m3-GGUF", "pipeline_tag": "sentence-similarity", "downloads": 9, "gguf": {"architecture": "bert", "total": 5e8}},
        {"id": "b/bge-reranker-GGUF", "pipeline_tag": "text-classification", "gguf": {"architecture": "bert"}},
        {"id": "c/llama-chat-GGUF", "pipeline_tag": "text-generation", "gguf": {"architecture": "llama"}},
        {"id": "ggml-org/bge-m3-Q8_0-GGUF", "tags": ["sentence-transformers"], "gguf": {"architecture": "bert"}},
    ]
    detail = {"id": "a/bge-m3-GGUF", "sha": "f" * 40, "cardData": {"license": "mit", "base_model": "BAAI/bge-m3"},
              "gguf": {"architecture": "bert", "context_length": 8192, "total": 5e8},
              "siblings": [{"rfilename": "bge-m3-F16.gguf", "size": 1000, "lfs": {"sha256": "1" * 64}},
                           {"rfilename": "bge-m3-Q8_0.gguf", "size": 600, "lfs": {"sha256": "2" * 64}},
                           {"rfilename": "mmproj-x.gguf", "size": 10, "lfs": {"sha256": "3" * 64}},
                           {"rfilename": "README.md", "size": 10}]}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/models/a/bge-m3-GGUF" in url:
            return httpx.Response(200, json=detail)
        if url.startswith("https://huggingface.co/api/models?"):
            assert request.url.params["filter"] == "gguf"
            return httpx.Response(200, json=listing)
        if "config_sentence_transformers.json" in url:
            return httpx.Response(200, json={"prompts": {"query": "q: ", "document": "d: "}})
        if "1_Pooling/config.json" in url:
            return httpx.Response(200, json={"pooling_mode_cls_token": True})
        return httpx.Response(404)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    found = hf_search.search("bge", http=http)["results"]
    assert [r["repo"] for r in found] == ["a/bge-m3-GGUF", "ggml-org/bge-m3-Q8_0-GGUF"]
    assert found[1]["catalog_id"] == "bge-m3" and found[0]["params_m"] == 500
    d = hf_search.model_detail("a/bge-m3-GGUF", http=http)
    assert [f["name"] for f in d["files"]] == ["bge-m3-Q8_0.gguf", "bge-m3-F16.gguf"] and d["recommended"] == "bge-m3-Q8_0.gguf"
    assert d["suggested"] == {"query_prefix": "q: ", "document_prefix": "d: ", "pooling": "cls", "source": "BAAI/bge-m3"}
    e = hf_search.make_user_entry(d, d["recommended"], "q: ", "d: ", "cls")
    assert e.id == "hf-a-bge-m3-q8_0" and e.user and e.file.bytes == 600 and e.source.revision == "f" * 40
    with pytest.raises(EmbeddingError):
        hf_search.make_user_entry({**d, "gated": True}, d["recommended"])


# -- Index übernehmen und Vergleich -------------------------------------------------------------------------------
def _library(engine, n=6):
    store = engine.store
    items = [{"key": f"I{i}", "data": {"itemType": "book", "title": f"Titel {i}", "collections": ["C1"],
                                         "creators": [{"lastName": f"Autor{i}"}], "date": "2020"}} for i in range(n)]
    store.upsert_items("users/0", items)
    texts = ["Schule Sozialarbeit Kooperation", "Gletscher Wasser Alpen", "Mindestlohn Arbeitsplätze",
             "Depression Bewegung Alter", "Transformer Aufmerksamkeit", "Maschinen Arbeiter Protest"]
    for i in range(n):
        store.replace_chunks("users/0", f"I{i}", f"A{i}", [Chunk(0, texts[i % len(texts)], 1, 1, "1")])
    return [dict(r) for r in store.con.execute("SELECT * FROM chunks ORDER BY id")]


def _put_space(engine, space, provider, model, rows, vecs, params):
    engine.store.ensure_space(space, provider, model, vecs.shape[1], params)
    engine.store.put_embeddings(space, [r["id"] for r in rows], vecs)


def test_adopt_index_from_other_provider(engine):
    rows = _library(engine)
    emb = engine.embedder()
    items = engine.store.items({(r["lib"], r["item_key"]) for r in rows})
    texts = [embedding_text(r, items.get((r["lib"], r["item_key"])), True) for r in rows]
    params = {"query_prefix": emb.query_prefix, "document_prefix": emb.document_prefix}
    same = emb.embed_documents(texts)
    _put_space(engine, "ollama:hash:256:aaaaaa", "ollama", "hash:latest", rows, same, params)
    _put_space(engine, "ollama:other:256:bbbbbb", "ollama", "other", rows, same, params)  # anderes Modell
    cands = spaces.candidates(engine, emb)
    assert [c["space"] for c in cands] == ["ollama:hash:256:aaaaaa"]
    chk = spaces.check(engine, "ollama:hash:256:aaaaaa", emb)
    assert chk["compatible"] and chk["cos_min"] > 0.999
    res = spaces.adopt(engine, "ollama:hash:256:aaaaaa", emb)
    assert res["moved"] == len(rows)
    by_space = {s["space"]: s["n"] for s in engine.store.spaces()}
    assert by_space[emb.space_id] == len(rows) and "ollama:hash:256:aaaaaa" not in by_space
    # Andere Vektoren: nicht übernehmbar
    rnd = np.random.default_rng(0).standard_normal((len(rows), 256)).astype(np.float32)
    _put_space(engine, "ollama:hash:256:cccccc", "ollama", "hash", rows, rnd, params)
    assert not spaces.check(engine, "ollama:hash:256:cccccc", emb)["compatible"]


def test_compare_two_models(engine, monkeypatch):
    from zotivity.retrieval import compare as cmp

    rows = _library(engine)
    emb = engine.embedder()
    items = engine.store.items({(r["lib"], r["item_key"]) for r in rows})
    texts = [embedding_text(r, items.get((r["lib"], r["item_key"])), True) for r in rows]
    params = {"query_prefix": "", "document_prefix": ""}
    active = engine.space()
    engine.store.put_embeddings(active, [r["id"] for r in rows], emb.embed_documents(texts))
    rnd = np.random.default_rng(1).standard_normal((3, 256)).astype(np.float32)
    _put_space(engine, "other:rnd:256:x", "other", "rnd", rows[:3], rnd, params)
    monkeypatch.setattr(cmp, "make_embedder", lambda cfg: emb)
    res = cmp.compare(engine, "Gletscher Wasser Alpen", active, "other:rnd:256:x", {}, k=3)
    assert res["a"]["hits"][0]["title"] == "Titel 1" and res["a"]["coverage"] == {"embedded": 6, "chunks": 6}
    assert res["b"]["coverage"] == {"embedded": 3, "chunks": 6} and res["b"]["warning"]
    assert len(res["b"]["hits"]) == 3 and res["shared_docs"] == sum(h["shared"] for h in res["a"]["hits"])
    with pytest.raises(ValueError):
        cmp.compare(engine, "x", active, "fehlt", {})


def test_project_embedding_pin(engine):
    pid = engine.ensure_project()
    engine.settings_store.update({"embedding": {"provider": "ollama", "model": "bge-m3"}})
    assert engine.apply_project_embedding(pid) is None  # kein eigenes Modell
    from zotivity.engine import project_embedding

    pin = project_embedding({"provider": "builtin", "model": "qwen3-embedding-0.6b", "base_url": "x"})
    assert pin == {"provider": "builtin", "model": "qwen3-embedding-0.6b", "query_prefix": None,
                   "document_prefix": None, "dimensions": None}
    engine.store.update_project(pid, embedding=pin)
    assert engine.store.project(pid)["embedding"]["model"] == "qwen3-embedding-0.6b"
    assert engine.apply_project_embedding(pid) == {"provider": "builtin", "model": "qwen3-embedding-0.6b"}
    assert engine.settings.embedding.provider == "builtin" and engine.apply_project_embedding(pid) is None
    engine.store.update_project(pid, embedding=None)
    assert engine.store.project(pid)["embedding"] is None


# -- Schnittstellen ------------------------------------------------------------------------------------------------
@pytest.fixture
def api(engine, fake_runtime, monkeypatch):
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    monkeypatch.setattr(benchmark, "cpu_score", lambda force=False: {"gflops": 400.0, "cpu": benchmark.cpu_name()})
    from zotivity.server.app import create_app

    with TestClient(create_app(engine)) as c:
        yield c


def _wait(c, job_id):
    for _ in range(300):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("Auftrag endet nicht")


def test_local_models_api_download_test_use(api, monkeypatch):
    d = api.get("/api/embedding/local").json()
    assert len(d["models"]) == 12 and d["machine"]["source"] == "cpu_test"
    bge = next(m for m in d["models"] if m["id"] == "bge-m3")
    assert bge["default"] and not bge["installed"] and bge["estimate"]["source"] == "estimated"
    assert bge["estimate"]["minutes_per_100_pages"] == 3.3 and bge["strengths"]
    assert {g["id"] for g in d["groups"]} >= {"recommended", "fast", "user"}
    # Eigenes Modell: Download (Ersatz-Server für Hugging Face) mit anschliessendem Kurztest
    content = gguf_bytes()
    model_catalog.save_user_model(user_entry(content))
    monkeypatch.setattr(model_store, "_http", lambda: serve(content))
    job = api.post("/api/embedding/local/hf-test-model-q8_0/download", headers=H).json()
    j = _wait(api, job["id"])
    assert j["status"] == "done", j
    assert j["counters"]["test"]["queries"] == 8 and j["counters"]["model"] == "hf-test-model-q8_0"
    m = next(x for x in api.get("/api/embedding/local").json()["models"] if x["id"] == "hf-test-model-q8_0")
    assert m["installed"] and m["test"] and m["estimate"]["source"] == "measured" and m["group"] == "user"
    # Verwenden: wird aktives Embedding-Modell
    assert api.post("/api/embedding/local/bge-m3/use", headers=H).status_code == 400  # nicht heruntergeladen
    r = api.post("/api/embedding/local/hf-test-model-q8_0/use", json={"dimensions": None}, headers=H)
    assert r.status_code == 200 and api.get("/api/settings").json()["embedding"]["model"] == "hf-test-model-q8_0"
    assert api.delete("/api/embedding/local/hf-test-model-q8_0", headers=H).status_code == 400  # aktiv
    api.put("/api/settings", json={"embedding": {"provider": "ollama", "model": "bge-m3"}}, headers=H)
    assert api.delete("/api/embedding/user/hf-test-model-q8_0", headers=H).json()["removed"]
    assert not model_store.installed()


def test_project_open_switches_embedding(api, engine):
    pid = engine.ensure_project()
    api.put("/api/settings", json={"embedding": {"provider": "ollama", "model": "bge-m3"}}, headers=H)
    r = api.put(f"/api/projects/{pid}", json={"embedding": {"provider": "builtin", "model": "bge-m3"}}, headers=H).json()
    assert r["embedding"]["model"] == "bge-m3" and r["embedding_switched"] == {"provider": "builtin", "model": "bge-m3"}
    api.put("/api/settings", json={"embedding": {"provider": "ollama", "model": "bge-m3"}}, headers=H)
    r = api.post(f"/api/projects/{pid}/open", headers=H).json()
    assert r["embedding_switched"]["model"] == "bge-m3"
    assert api.get("/api/settings").json()["embedding"]["provider"] == "builtin"
    r = api.put(f"/api/projects/{pid}", json={"embedding": None}, headers=H).json()
    assert r["embedding"] is None
