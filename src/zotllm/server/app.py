"""Lokaler Webdienst: Oberfläche und Schnittstelle für das Zotero-Plugin.

Sicherheit: Der Dienst lauscht nur auf 127.0.0.1. Gegen DNS-Rebinding wird der
Host-Header geprüft; schreibende Anfragen brauchen den Header ``X-ZotLLM``.
Fremde Webseiten können diesen Header nicht ohne CORS-Vorabprüfung setzen, und
CORS ist nicht freigegeben – damit sind CSRF-Angriffe aus dem Browser ausgeschlossen.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from zotllm import __version__, paths
from zotllm.i18n import tr, tr_exact, tr_fields
from zotllm.catalog import EMBEDDING_PRESETS, PROVIDERS, sort_chat_models
from zotllm.embeddings import EmbeddingError, make_embedder
from zotllm.embeddings.ollama import ollama_available, ollama_pull
from zotllm.engine import Engine
from zotllm.index import duplicates
from zotllm.index.indexer import Indexer
from zotllm.index.store import SearchFilter
from zotllm.keystore import SecretStoreError, get_store
from zotllm.llm import LLMError, make_chat_model
from zotllm.rag import AskOptions, ChatService, ReviewService
from zotllm.rag.sources import build_sources
from zotllm.research.api import install as install_research
from zotllm.research.service import ResearchService
from zotllm.research_adapters import build_research_service
from zotllm.retrieval import Searcher
from zotllm.service import BackgroundScheduler, launcher_command
from zotllm.settings import EmbeddingSettings, Settings
from zotllm.updates import version_tuple
from zotllm.index.store import strip_bidi
from zotllm.zotero import (ZoteroAuthRequired, ZoteroError, ZoteroUnavailable, opens_in_reader, zotero_open_pdf_url,
                              zotero_select_url)
from zotllm.zotero.tree import describe_sources, fetch_tree

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
CSRF_HEADER = "x-zotllm"
LEGACY_CSRF_HEADER = "x-zoterollm"  # Plugin und Installer bis 0.7.3 (damals „ZoteroLLM“)
STATIC_VERSIONED = re.compile(r"^/static/v\d[\w.+-]*/(.+)$")  # v0.9.0 – nicht der Ordner „vendor“
# Ältere Plugins kennen die Schnittstelle /zotllm/uris (Word-Belege) noch nicht; bis 0.7.3 hiess das Plugin „ZoteroLLM“
PLUGIN_MIN_VERSION = "0.8.0"
RENAMED_IN = "0.8.0"


def create_app(engine: Engine | None = None, on_exit=None, exit_after_minutes: int | None = None,
               on_open_ui=None, on_idle_exit=None, research: ResearchService | None = None) -> FastAPI:
    """on_exit: beendet den Dienst; on_open_ui(params): zeigt das Programmfenster (nur im Desktop-Programm);
    on_idle_exit: Beenden, weil Zotero geschlossen ist – darf mit False ablehnen (Standard: on_exit);
    research: Dienst des Moduls „Recherche“ (Standard: research.db im Datenordner, research_adapters.py)."""
    engine = engine or Engine()
    research = research or build_research_service(engine)
    indexer = Indexer(engine)
    try:  # Schnappschüsse neben einer PDF gleich beim Start einordnen (sonst erst beim nächsten Indexieren)
        indexer.reconcile_snapshots()
    except Exception:  # noqa: BLE001
        log.exception("Schnappschüsse nicht abgeglichen")
    chat = ChatService(engine)
    reviews = ReviewService(engine)
    scheduler = BackgroundScheduler(engine, on_exit=on_idle_exit or on_exit, exit_after_minutes=exit_after_minutes)
    keys = get_store()

    def repair_references():
        """Belege auf in Zotero gelöschte Einträge auf eine noch vorhandene Kopie umstellen (references.py)."""
        from zotllm import references

        try:
            references.repair(engine)
        except Exception:  # noqa: BLE001 - beim Öffnen eines Forschungsstands erneut
            log.exception("Belege auf gelöschte Einträge nicht umgestellt")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler.start()
        threading.Thread(target=refresh_model_catalog, name="model-catalog", daemon=True).start()
        threading.Thread(target=repair_references, name="references", daemon=True).start()
        yield
        scheduler.stop()
        engine.shutdown()
        research.store.close()

    app = FastAPI(title="ZotLLM", version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.engine = engine
    app.state.research = research

    # -- Sicherheit ---------------------------------------------------------------------
    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").split(":")[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1", "testserver"):
            return PlainTextResponse("Ungültiger Host", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and "1" not in (request.headers.get(CSRF_HEADER),
                                                                           request.headers.get(LEGACY_CSRF_HEADER)):
            return PlainTextResponse("Header X-ZotLLM fehlt", status_code=403)
        # /static/v<version>/… → /static/…: die Oberfläche lädt ihre Module unter einem Pfad je Version, damit nach
        # einem Update nichts aus dem Zwischenspeicher der alten Version stammt (index.html setzt den Pfad)
        m = STATIC_VERSIONED.match(request.scope["path"])
        if m:
            request.scope["path"] = "/static/" + m.group(1)
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            # Immer nachfragen (ETag → 304): sonst mischt der Browser nach einem Update alte und neue Module,
            # und die Oberfläche startet nicht oder reagiert nicht mehr
            response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(ZoteroUnavailable)
    async def _zu(_, e):
        return JSONResponse({"detail": tr(str(e)), "kind": "zotero_unavailable"}, status_code=503)

    @app.exception_handler(ZoteroAuthRequired)
    async def _za(_, e):
        return JSONResponse({"detail": tr(str(e)), "kind": "zotero_auth"}, status_code=403)

    @app.exception_handler(ZoteroError)
    async def _ze(_, e):
        return JSONResponse({"detail": tr(str(e)), "kind": "zotero"}, status_code=502)

    @app.exception_handler(LLMError)
    async def _le(_, e):
        return JSONResponse({"detail": tr(str(e)), "kind": e.kind}, status_code=502)

    @app.exception_handler(EmbeddingError)
    async def _ee(_, e):
        return JSONResponse({"detail": tr(str(e)), "kind": "embedding"}, status_code=502)

    @app.exception_handler(SecretStoreError)
    async def _se(_, e):
        return JSONResponse({"detail": tr(str(e)), "kind": "keystore"}, status_code=500)

    @app.exception_handler(ValidationError)
    async def _ve(_, e):
        return JSONResponse({"detail": e.errors(include_url=False, include_context=False)}, status_code=422)

    @app.exception_handler(ValueError)
    async def _val(_, e):
        return JSONResponse({"detail": tr(str(e))}, status_code=400)

    @app.exception_handler(HTTPException)
    async def _http(_, e):
        detail = tr(e.detail) if isinstance(e.detail, str) else e.detail
        return JSONResponse({"detail": detail}, status_code=e.status_code, headers=getattr(e, "headers", None))

    def job_or_409(kind: str, title: str, fn, group: str | None):
        try:
            return engine.jobs.start(kind, title, fn, group=group).as_dict()
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e

    # -- Oberfläche -------------------------------------------------------------------------
    index_html = (STATIC / "index.html").read_text(encoding="utf-8").replace('"/static/', f'"/static/v{__version__}/')

    @app.get("/", include_in_schema=False)
    def index():
        return Response(index_html, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # -- Status & Einstellungen ------------------------------------------------------------
    def provider_ready(pid: str) -> bool:
        info = PROVIDERS.get(pid)
        return info is not None and (not info.needs_key or bool(keys.get(pid)))

    def heal_llm_choice() -> None:
        """Ist für das eingestellte Sprachmodell kein Schlüssel da, aber für einen anderen Anbieter schon,
        auf diesen umstellen (z. B. Schlüssel gespeichert, bevor die automatische Umstellung existierte)."""
        llm = engine.settings.llm
        if provider_ready(llm.provider) and provider_ready(llm.helper_provider):
            return
        try:
            with_key = [p for p in PROVIDERS.values() if p.chat and p.needs_key and p.default_main and keys.get(p.id)]
        except SecretStoreError:
            return
        if not with_key:
            return
        info = with_key[0]
        patch = {}
        if not provider_ready(llm.provider):
            patch.update(provider=info.id, model=info.default_main)
        if not provider_ready(llm.helper_provider):
            patch.update(helper_provider=info.id, helper_model=info.default_helper or info.default_main)
        engine.settings_store.update({"llm": patch})
        log.info("Sprachmodell auf %s umgestellt (kein Schlüssel für den bisherigen Anbieter)", info.label)

    heal_llm_choice()

    def zotero_state() -> dict:
        zot = engine.zotero().status()
        zot["write_access"] = False
        zot["write_session"] = False
        if zot.get("server_id"):
            try:
                client = engine.zotero()
                zot["write_access"] = client.has_write_access()
                # Nur für diese Sitzung freigegeben (in Zotero ohne „Entscheidung merken“)
                zot["write_session"] = zot["write_access"] and not client.keystore.get(client._key_name())
            except Exception:  # noqa: BLE001
                pass
        if zot.get("message"):
            zot["message"] = tr(zot["message"])
        return zot

    coverage_cache: dict = {"at": 0.0, "key": None, "data": None}

    def index_coverage(space: str | None, force: bool = False) -> dict | None:
        """Kennzahlen über alle Korpora für das aktive Modell (kurz zwischengespeichert, damit Statusleiste und
        Ansicht Index dieselben Zahlen zeigen; ein beendeter Lauf macht den Zwischenspeicher ungültig)."""
        if not engine.store.corpora():
            return None
        ttl = 5 if engine.jobs.running("index") else 20
        key = (space, engine.store.get_meta("index_checked_at"), engine.store.duplicates_gen)
        if (not force and coverage_cache["data"] is not None and coverage_cache["key"] == key
                and time.time() - coverage_cache["at"] < ttl):
            return coverage_cache["data"]
        data = engine.store.scope_stats(indexer.scope(), space)
        coverage_cache.update(at=time.time(), key=key, data=data)
        return data

    def embed_estimate(chunks: int) -> float | None:
        """Geschätzte Sekunden, um so viele Abschnitte mit dem aktiven Modell einzubetten."""
        if not chunks:
            return 0.0
        space = engine.embedding_status().get("space")
        rate = engine.store.get_meta(f"embed_rate:{space}") if space else None
        if rate:
            return chunks / float(rate)
        cfg = engine.settings.embedding
        if cfg.provider == "builtin":
            entry = model_catalog.get(cfg.model)
            if entry is not None:
                rec = model_store.record(entry.id) or {}
                est = benchmark.estimate(entry, benchmark.machine_factor()["factor"], rec.get("test"))
                if est.get("tok_per_s"):
                    return chunks * engine.settings.chunking.chunk_tokens * 1.15 / est["tok_per_s"]
        return None

    @app.get("/api/status")
    def status():
        settings = engine.settings
        emb = engine.embedding_status()
        stats = {**engine.store.stats(emb.get("space")), **scope_info()}
        cov = index_coverage(emb.get("space"))
        if cov:
            stats["coverage"] = {k: cov[k] for k in ("documents", "indexed", "to_embed", "refresh", "pending", "chunks",
                                                     "embedded")}
        llm = settings.llm
        return {
            "version": __version__,
            "zotero": zotero_state(),
            "ollama": ollama_available(settings.embedding.base_url if settings.embedding.provider == "ollama"
                                       else settings.llm.base_urls.get("ollama")),
            "embedding": tr_fields(emb, "error"),
            "index": stats,
            "llm": {"provider": llm.provider, "provider_label": PROVIDERS.get(llm.provider, PROVIDERS["ollama"]).label,
                    "model": llm.model, "key": provider_ready(llm.provider),
                    "helper_provider": llm.helper_provider, "helper_model": llm.helper_model,
                    "helper_key": provider_ready(llm.helper_provider)},
            "corpora": len(engine.store.corpora()),
            # Suchkatalog: Stand und ob Zotero seither geändert wurde (Versionsvergleich im Hintergrundplaner)
            "catalog": {"synced_at": float(cat_at) if (cat_at := engine.store.get_meta("catalog_synced_at")) else None,
                        "zotero_changed": bool(scheduler.catalog_changed), "libraries": list(scheduler.catalog_changed)},
            "indexing_mode": settings.indexing.mode,
            "jobs": [j for j in engine.jobs.list() if j["status"] in ("queued", "running")],
            "index_queue": queue_list(),
            "keystore": keys.backend_info(),
        }

    def index_detail(x: dict, label: str | None) -> str:
        """„3 von 10 Dokumenten mit bge-m3 durchsuchbar · 2 Texte einzubetten · 5 Texte zu aktualisieren“."""
        def n_texts(n: int, what: str) -> str:
            return tr(f"1 Text {what}") if n == 1 else tr(f"{n} Texte {what}")

        parts = [tr(f"{x['indexed'] + x['refresh']} von {x['documents']} Dokumenten mit {label} durchsuchbar")]
        if x["to_embed"]:
            parts.append(n_texts(x["to_embed"], "einzubetten"))
        if x["refresh"]:
            parts.append(n_texts(x["refresh"], "zu aktualisieren"))
        return " · ".join(parts)

    @app.get("/api/setup")
    def setup():
        """Einrichtungs-Checkliste für die Startseite."""
        settings = engine.settings
        zot = zotero_state()
        emb = engine.embedding_status()
        llm = settings.llm
        corpora = engine.store.corpora()
        all_stats = engine.store.scope_stats(indexer.scope(), emb.get("space")) if corpora else None
        plugin_seen = engine.store.get_meta("plugin_seen")
        plugin_version = engine.store.get_meta("plugin_version") or "0"
        plugin_old = version_tuple(plugin_version) < version_tuple(PLUGIN_MIN_VERSION)
        main_label = PROVIDERS.get(llm.provider, PROVIDERS["ollama"]).label
        steps = [
            {"id": "zotero", "title": "Zotero verbinden", "done": bool(zot.get("local_api")),
             "detail": (f"Verbunden mit Zotero {zot.get('version') or ''}" if zot.get("local_api")
                        else zot.get("message") or "Zotero läuft nicht.")},
            {"id": "llm", "title": "Sprachmodell und API-Schlüssel",
             "done": provider_ready(llm.provider) and provider_ready(llm.helper_provider),
             "detail": (f"{main_label} · {llm.model}" if provider_ready(llm.provider)
                        else f"Für {main_label} ist kein API-Schlüssel gespeichert.")},
            {"id": "embedding", "title": "Embedding-Modell", "done": bool(emb.get("ok")),
             "detail": f"{emb.get('label')} ({PROVIDERS[emb['provider']].label if emb.get('provider') in PROVIDERS else emb.get('provider')})"
             if emb.get("ok") else emb.get("error", "")},
            {"id": "corpus", "title": "Wissenskorpus anlegen", "done": bool(corpora),
             "detail": ", ".join(c["name"] for c in corpora) if corpora else
             "Wähle Sammlungen aus deiner Zotero-Bibliothek, die durchsucht werden sollen."},
            # Texte, die nur auf erneutes Lesen warten („zu aktualisieren“), sind durchsuchbar und halten nichts auf
            {"id": "index", "title": "Texte indexieren",
             "done": bool(all_stats and all_stats["documents"] and not all_stats["pending"] and not all_stats["to_embed"]),
             "detail": index_detail(all_stats, emb.get("label")) if all_stats else "Nach dem Anlegen eines Korpus."},
            {"id": "write", "title": "Schreibzugriff auf Zotero", "optional": True,
             "done": bool(zot.get("write_access")),
             "detail": "Für Auswertungsblätter als Notizen und Sammlungen aus dem Forschungsstand."},
            {"id": "plugin", "title": "Zotero-Plugin", "optional": True, "done": bool(plugin_seen) and not plugin_old,
             "detail": ("Das Plugin heisst jetzt ZotLLM: in Zotero das alte Plugin „ZoteroLLM“ entfernen und das neue "
                        "installieren." if plugin_seen and version_tuple(plugin_version) < version_tuple(RENAMED_IN) else
                        f"Version {plugin_version} ist veraltet – bitte neu installieren (u. a. für genaue Word-Belege)."
                        if plugin_seen and plugin_old else
                        "Rechtsklick-Menüs in Zotero und Start von ZotLLM mit Zotero.")},
        ]
        for s in steps:
            s["title"] = tr(s["title"])
            # Beim Korpus stehen sonst die Namen der Korpora – nur den festen Hinweis übersetzen
            s["detail"] = tr_exact(s["detail"]) if s["id"] == "corpus" else tr(s["detail"])
        return {"steps": steps, "ready": all(s["done"] for s in steps if not s.get("optional"))}

    @app.get("/api/settings")
    def get_settings():
        return engine.settings.model_dump()

    @app.put("/api/settings")
    def put_settings(patch: dict = Body(...)):
        return engine.settings_store.update(patch).model_dump()

    @app.get("/api/settings/defaults")
    def settings_defaults():
        """Standardwerte – für „zurücksetzen“ und Hinweise in den Experteneinstellungen."""
        return Settings().model_dump()

    @app.get("/api/catalog")
    def catalog():
        return {
            "providers": [
                {"id": p.id, "label": p.label, "needs_key": p.needs_key, "key_url": p.key_url, "chat": p.chat,
                 "embeddings": p.embeddings, "default_base_url": p.default_base_url,
                 "chat_models": list(p.chat_models), "embedding_models": list(p.embedding_models), "notes": p.notes}
                for p in PROVIDERS.values()
            ],
            "embedding_presets": {k: {"query_prefix": v.query_prefix, "document_prefix": v.document_prefix}
                                  for k, v in EMBEDDING_PRESETS.items()},
        }

    # -- API-Schlüssel -------------------------------------------------------------------------
    @app.get("/api/keys")
    def list_keys():
        out = {}
        for p in PROVIDERS.values():
            if p.needs_key or p.id == "openai_compatible":
                out[p.id] = {"stored": keys.source(p.id) is not None, "source": keys.source(p.id),
                             "masked": keys.masked(p.id)}
        return {"backend": keys.backend_info(), "keys": out}

    @app.put("/api/keys/{provider}")
    def set_key(provider: str, body: dict = Body(...)):
        if provider not in PROVIDERS:
            raise HTTPException(404, "Unbekannter Anbieter")
        keys.set(provider, str(body.get("key", "")))
        engine.reset_embedder()
        # Hat der eingestellte Anbieter keinen Schlüssel, auf den neuen Anbieter umstellen
        switched = None
        info = PROVIDERS[provider]
        llm = engine.settings.llm
        if info.chat and info.default_main:
            patch = {}
            if not provider_ready(llm.provider) or llm.provider == provider and not llm.model:
                patch.update(provider=provider, model=info.default_main)
            if not provider_ready(llm.helper_provider):
                patch.update(helper_provider=provider, helper_model=info.default_helper or info.default_main)
            if patch:
                new = engine.settings_store.update({"llm": patch}).llm
                switched = {"provider": info.label, "model": new.model, "helper_model": new.helper_model}
        return {"stored": True, "masked": keys.masked(provider), "switched": switched}

    @app.delete("/api/keys/{provider}")
    def delete_key(provider: str):
        deleted = keys.delete(provider)
        engine.reset_embedder()
        return {"deleted": deleted}

    @app.get("/api/providers/{provider}/models")
    def provider_models(provider: str):
        info = PROVIDERS.get(provider)
        if not info:
            raise HTTPException(404, "Unbekannter Anbieter")
        loaded: list[str] = []
        if provider_ready(provider):
            loaded = make_chat_model(provider, "probe", engine.settings.llm).list_models()
        models = sort_chat_models(provider, loaded or list(info.chat_models))
        return {"models": models, "loaded": bool(loaded), "default_main": info.default_main,
                "default_helper": info.default_helper}

    @app.post("/api/providers/{provider}/test")
    def provider_test(provider: str, body: dict = Body(default={})):
        info = PROVIDERS.get(provider)
        if not info:
            raise HTTPException(404, "Unbekannter Anbieter")
        model = make_chat_model(provider, body.get("model") or info.default_main, engine.settings.llm)
        return model.test()

    # -- Embeddings -----------------------------------------------------------------------------
    @app.get("/api/embedding/models")
    def embedding_models(provider: str | None = None):
        cfg = engine.settings.embedding.model_copy()
        if provider:
            cfg.provider = provider
        try:
            return {"models": make_embedder(cfg).list_models()}
        except EmbeddingError:
            return {"models": []}

    @app.post("/api/embedding/test")
    def embedding_test(body: dict = Body(default={})):
        cfg = EmbeddingSettings.model_validate({**engine.settings.embedding.model_dump(), **body})
        return make_embedder(cfg).test()

    @app.get("/api/embedding/spaces")
    def spaces():
        """Gespeicherte Indizes je Embedding-Modell, mit Grösse des Modells (Ollama) und der Vektoren."""
        import httpx

        active = engine.embedding_status().get("space")
        sizes: dict[str, int] = {}
        if any(s["provider"] == "ollama" for s in engine.store.spaces()):
            try:
                from zotllm.embeddings.ollama import ollama_base_url

                r = httpx.get(f"{ollama_base_url(engine.settings.embedding.base_url)}/api/tags", timeout=3, trust_env=False)
                for m in r.json().get("models", []):
                    sizes[m["name"]] = m.get("size") or 0
                    sizes.setdefault(m["name"].removesuffix(":latest"), m.get("size") or 0)
            except Exception:  # noqa: BLE001 - Ollama nicht erreichbar: ohne Grössenangabe
                pass
        from zotllm.embeddings import model_store

        local = model_store.installed()
        out = []
        for s in engine.store.spaces():
            model_bytes = (sizes.get(s["model"]) if s["provider"] == "ollama"
                           else (local.get(s["model"]) or {}).get("bytes") if s["provider"] == "builtin" else None)
            label = engine.embedding_label(SimpleNamespace(provider=s["provider"], model=s["model"]))
            out.append({**s, "label": label, "model_bytes": model_bytes, "index_bytes": int(s["n"]) * int(s["dim"] or 0) * 2})
        return {"active": active, "spaces": out}

    @app.post("/api/embedding/spaces/activate")
    def space_activate(body: dict = Body(...)):
        """Das Modell eines gespeicherten Index wieder verwenden (z. B. „zurück zu bge-m3“)."""
        s = next((x for x in engine.store.spaces() if x["space"] == body.get("space")), None)
        if not s:
            raise HTTPException(404, "Nicht gefunden")
        params = json.loads(s["params"] or "{}")
        base = engine.settings.embedding.model_dump()
        explicit = {"query_prefix": params.get("query_prefix", ""), "document_prefix": params.get("document_prefix", "")}
        tries = [{"query_prefix": None, "document_prefix": None, "dimensions": None},
                 {"query_prefix": None, "document_prefix": None, "dimensions": int(s["dim"])},
                 {**explicit, "dimensions": None}, {**explicit, "dimensions": int(s["dim"])}]
        chosen = tries[2]
        for t in tries:  # möglichst die Standard-Präfixe des Modells verwenden, sonst die gespeicherten
            cfg = EmbeddingSettings.model_validate({**base, **t, "provider": s["provider"], "model": s["model"]})
            try:
                emb = make_embedder(cfg)
            except EmbeddingError as e:
                raise HTTPException(400, str(e)) from e
            if emb._dim is None:
                emb._dim = int(s["dim"])
            if emb.space_id == s["space"]:
                chosen = t
                break
        engine.settings_store.update({"embedding": {**chosen, "provider": s["provider"], "model": s["model"]}})
        return {"embedding": engine.embedding_status()}

    @app.delete("/api/embedding/spaces/{space:path}")
    def delete_space(space: str):
        if space == engine.embedding_status().get("space"):
            raise HTTPException(400, "Der aktive Embedding-Raum kann nicht gelöscht werden.")
        engine.store.delete_space(space)
        return {"deleted": space}

    @app.post("/api/ollama/pull")
    def pull(body: dict = Body(...)):
        model = body.get("model")
        if not model:
            raise HTTPException(400, "Modellname fehlt")
        base = engine.settings.embedding.base_url

        def run(job):
            job.update(phase="Download", message=model)
            for msg in ollama_pull(base, model):
                job.check()
                total, done = msg.get("total"), msg.get("completed")
                job.update(message=msg.get("status", ""), total=total or 0, done=done or 0)
            return {"model": model}

        return job_or_409("pull", f"Ollama: {model} herunterladen", run, group="pull")

    # -- Eingebaute Embedding-Modelle (llama.cpp) --------------------------------------------------------
    from zotllm.embeddings import benchmark, hf_search, model_catalog, model_store
    from zotllm.embeddings.llama_runtime import get_runtime
    from zotllm.index import spaces as index_spaces

    def refresh_model_catalog() -> dict | None:
        """Zentralen Modellkatalog laden, falls eine Adresse eingestellt ist (beim Start im Hintergrund)."""
        if not engine.settings.model_catalog_url:
            return None
        try:
            return model_catalog.refresh(engine.settings.model_catalog_url)
        except Exception as e:  # noqa: BLE001 - ohne Netz gilt der zuletzt geladene bzw. mitgelieferte Katalog
            log.warning("Modellkatalog nicht geladen: %s", e)
            return {"error": str(e)}

    def _entry(mid: str):
        entry = model_catalog.get(mid)
        if entry is None:
            raise HTTPException(404, "Modell nicht im Katalog")
        return entry

    def _builtin_embedder(entry):
        """Embedder mit den aktuellen Einstellungen (Threads usw.); für das aktive Modell genau dessen Einstellung."""
        cur = engine.settings.embedding
        if cur.provider == "builtin" and cur.model == entry.id:
            return make_embedder(cur)
        return make_embedder(EmbeddingSettings(provider="builtin", model=entry.id, num_thread=cur.num_thread,
                                               parallel=cur.parallel, keep_alive_minutes=cur.keep_alive_minutes))

    def _model_jobs() -> dict[str, dict]:
        out = {}
        for j in engine.jobs.list():
            mid = (j.get("counters") or {}).get("model")
            if mid and j["kind"] in ("model-download", "model-test", "model-adopt") and j["status"] in ("queued", "running"):
                out[mid] = j
        return out

    @app.get("/api/embedding/local")
    def local_models():
        """Modellkatalog mit Download-Stand, Zeitschätzung bzw. Messung, Speicherbedarf und Index je Modell."""
        lang = "de" if engine.settings.language == "de" else "en"
        installed = model_store.installed()
        factor = benchmark.machine_factor(installed)
        spaces_by_id = {s["space"]: s for s in engine.store.spaces()}
        n_chunks = engine.store.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        cur = engine.settings.embedding
        jobs = _model_jobs()
        cat = model_catalog.current()
        models = []
        for m in model_catalog.all_models():
            rec = installed.get(m.id)
            test = (rec or {}).get("test")
            space_id, vectors = None, 0
            dim = ((rec or {}).get("gguf") or {}).get("dim") or m.dim
            # Präfixe, mit denen das Modell tatsächlich einbettet (eigene Werte, beim aktiven Modell die Einstellung)
            prefixes = {k: getattr(m.runtime, k) for k in model_catalog.PREFIX_KEYS}
            if rec:
                try:
                    emb = _builtin_embedder(m)
                    space_id, dim = emb.space_id, emb.dim
                    vectors = int((spaces_by_id.get(space_id) or {}).get("n") or 0)
                    prefixes = {"query_prefix": emb.query_prefix, "document_prefix": emb.document_prefix}
                except EmbeddingError:
                    pass
            default_rt = None if m.user else model_catalog.catalog_runtime(m.id)
            models.append({
                "id": m.id, "name": m.name, "vendor": m.vendor, "year": m.year, "group": m.group, "default": m.default,
                "params_m": m.params_m, "dim": dim, "matryoshka": m.matryoshka, "context": m.context,
                "languages": m.text("languages", lang), "license": m.license, "mteb": m.mteb,
                "mteb_note": m.text("mteb_note", lang), "strengths": m.text("strengths", lang),
                "disciplines": m.text("disciplines", lang), "notes": m.text("notes", lang), "model_url": m.model_url,
                "repo": m.source.repo, "revision": m.source.revision, "official": m.source.official,
                "file": m.file.name, "quant": m.file.quant, "bytes": m.file.bytes, "user": m.user, "origin": m.origin,
                "runtime": m.runtime.model_dump(), "reference": m.reference.model_dump(), "prefixes": prefixes,
                "default_prefixes": {k: getattr(default_rt, k) for k in model_catalog.PREFIX_KEYS} if default_rt else None,
                "installed": bool(rec), "partial_bytes": 0 if rec else model_store.partial_bytes(m),
                "test": test, "estimate": benchmark.estimate(m, factor["factor"], test),
                "ram": benchmark.ram_estimate(m, test),
                "index": {"space": space_id, "vectors": vectors, "bytes": vectors * int(dim or 0) * 2,
                          "estimated_bytes": int(n_chunks) * int(dim or 0) * 2},
                "active": cur.provider == "builtin" and cur.model == m.id,
                "job": jobs.get(m.id),
            })
        folder = paths.models_dir()
        return {
            "catalog": {"version": cat.version, "origin": cat.models[0].origin if cat.models else "bundled",
                        "reference": cat.reference, "url": engine.settings.model_catalog_url},
            "groups": model_catalog.groups(lang), "models": models, "runtime": get_runtime().info(),
            "machine": {**factor, "cpu": benchmark.cpu_name()}, "chunks": int(n_chunks),
            "disk": {"folder": str(folder), "used_bytes": model_store.used_bytes(),
                     "free_bytes": shutil.disk_usage(folder).free},
            "tokens_per_100_pages": benchmark.TOKENS_PER_100_PAGES,
        }

    def _run_short_test(job, entry) -> dict:
        job.counters["model"] = entry.id
        res = benchmark.short_test(_builtin_embedder(entry), job)
        model_store.set_test(entry.id, res)
        job.counters["test"] = res
        return res

    @app.post("/api/embedding/local/{mid}/download")
    def local_download(mid: str):
        entry = _entry(mid)
        if model_store.record(mid):
            raise HTTPException(400, "Das Modell ist bereits heruntergeladen.")

        def run(job):
            job.counters["model"] = mid
            model_store.download(entry, job)
            # Kurztest gleich anschliessen: ersetzt die Schätzung durch einen Messwert
            try:
                return {"model": mid, "test": _run_short_test(job, entry)}
            except EmbeddingError as e:
                job.note(f"Kurztest fehlgeschlagen: {e}")
                return {"model": mid, "test_error": str(e)}

        return job_or_409("model-download", f"Download: {entry.name}", run, group=f"model-download:{mid}")

    @app.delete("/api/embedding/local/{mid}/partial")
    def local_discard_partial(mid: str):
        model_store.discard_partial(_entry(mid))
        return {"discarded": mid}

    @app.post("/api/embedding/local/{mid}/test")
    def local_test(mid: str):
        entry = _entry(mid)
        if not model_store.record(mid):
            raise HTTPException(400, "Das Modell ist noch nicht heruntergeladen.")
        return job_or_409("model-test", f"Kurztest: {entry.name}", lambda job: _run_short_test(job, entry),
                          group="model-test")

    @app.delete("/api/embedding/local/{mid}")
    def local_delete(mid: str):
        cur = engine.settings.embedding
        if cur.provider == "builtin" and cur.model == mid:
            raise HTTPException(400, "Das aktive Modell kann nicht gelöscht werden – zuerst ein anderes wählen.")
        path = model_store.model_path(mid)
        if path is not None:
            get_runtime().stop_model(str(path))
        entry = model_catalog.get(mid)
        if entry is not None:
            model_store.discard_partial(entry)
        return {"deleted": model_store.delete(mid)}

    @app.post("/api/embedding/local/{mid}/use")
    def local_use(mid: str, body: dict = Body(default={})):
        entry = _entry(mid)
        if not model_store.record(mid):
            raise HTTPException(400, "Das Modell ist noch nicht heruntergeladen.")
        dims = body.get("dimensions")
        if dims is not None and int(dims) not in entry.matryoshka:
            raise HTTPException(400, "Diese Vektorlänge unterstützt das Modell nicht.")
        engine.settings_store.update({"embedding": {"provider": "builtin", "model": mid, "query_prefix": None,
                                                    "document_prefix": None, "dimensions": dims}})
        return {"embedding": engine.embedding_status(), "adopt": adopt_candidates()}

    def adopt_candidates() -> list[dict]:
        """Bestehende Indizes desselben Modells (z. B. von Ollama), solange der aktive Index leer ist."""
        try:
            emb = engine.embedder()
        except EmbeddingError:
            return []
        active = next((s for s in engine.store.spaces() if s["space"] == emb.space_id), None)
        if active and active["n"]:
            return []
        return [{"space": s["space"], "provider": s["provider"], "model": s["model"], "vectors": s["n"]}
                for s in index_spaces.candidates(engine, emb)]

    @app.get("/api/embedding/adopt")
    def adopt_list():
        return {"candidates": adopt_candidates()}

    @app.post("/api/embedding/adopt")
    def adopt_run(body: dict = Body(...)):
        source = str(body.get("space") or "")
        if source not in {c["space"] for c in adopt_candidates()}:
            raise HTTPException(400, "Dieser Index lässt sich nicht übernehmen.")
        if engine.jobs.running("index"):
            raise HTTPException(409, "Bitte warten, bis die Indexierung beendet ist.")

        def run(job):
            emb = engine.embedder()
            job.counters["model"] = emb.model
            job.update(phase="Vergleich", message="Stichprobe wird neu eingebettet …")
            result = index_spaces.check(engine, source, emb)
            if result["compatible"]:
                job.update(phase="Übernahme", message="Index wird übernommen …")
                result = {**result, **index_spaces.adopt(engine, source, emb)}
            job.counters["result"] = {"adopted": bool(result["compatible"]), **result}
            return job.counters["result"]

        return job_or_409("model-adopt", "Index übernehmen", run, group="index")

    @app.post("/api/embedding/catalog/refresh")
    def catalog_refresh():
        if not engine.settings.model_catalog_url:
            raise HTTPException(400, "Keine Adresse für den Modellkatalog eingestellt.")
        try:
            return model_catalog.refresh(engine.settings.model_catalog_url)
        except model_catalog.CatalogError as e:
            raise HTTPException(502, str(e)) from e

    @app.post("/api/system/cpu-test")
    def cpu_test():
        return benchmark.cpu_score(force=True)

    # -- Namenssuche auf Hugging Face und eigene Modelle --------------------------------------------------
    @app.get("/api/embedding/hf/search")
    def hf_search_models(q: str = ""):
        return hf_search.search(q)

    @app.get("/api/embedding/hf/model")
    def hf_model(repo: str):
        if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
            raise HTTPException(400, "Ungültiger Name eines Repositorys")
        return hf_search.model_detail(repo)

    @app.post("/api/embedding/hf/add")
    def hf_add(body: dict = Body(...)):
        repo = str(body.get("repo") or "")
        if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
            raise HTTPException(400, "Ungültiger Name eines Repositorys")
        detail = hf_search.model_detail(repo)
        entry = hf_search.make_user_entry(detail, str(body.get("file") or detail.get("recommended") or ""),
                                          str(body.get("query_prefix") or ""), str(body.get("document_prefix") or ""),
                                          str(body.get("pooling") or ""))
        try:
            entry = model_catalog.save_user_model(entry)
        except model_catalog.CatalogError as e:
            raise HTTPException(400, str(e)) from e
        out = {"model": entry.id}
        if body.get("download"):
            out["job"] = local_download(entry.id)
        return out

    def after_prefix_change(mid: str) -> bool:
        """Geänderte Präfixe gelten sofort; beim aktiven Modell weicht eine frühere feste Einstellung den neuen
        Werten (sonst bliebe alles beim Alten). Liefert, ob das aktive Modell betroffen ist (neuer Index)."""
        cur = engine.settings.embedding
        active = cur.provider == "builtin" and cur.model == mid
        if active and (cur.query_prefix is not None or cur.document_prefix is not None):
            engine.settings_store.update({"embedding": {"query_prefix": None, "document_prefix": None}})
        engine.reset_embedder()
        return active

    @app.put("/api/embedding/user/{mid}")
    def user_model_update(mid: str, body: dict = Body(...)):
        runtime_patch = {k: body[k] for k in ("query_prefix", "document_prefix", "pooling") if k in body}
        try:
            entry = model_catalog.update_user_model(mid, runtime=runtime_patch)
        except (model_catalog.CatalogError, ValidationError) as e:
            raise HTTPException(400, str(e)) from e
        return {"model": entry.id, "runtime": entry.runtime.model_dump(), "active": after_prefix_change(mid)}

    @app.put("/api/embedding/local/{mid}/prefixes")
    def local_prefixes(mid: str, body: dict = Body(...)):
        """Präfixe eines Katalogmodells ändern (eigene Modelle: /api/embedding/user/{mid})."""
        entry = _entry(mid)
        if entry.user:
            return user_model_update(mid, {k: body[k] for k in model_catalog.PREFIX_KEYS if k in body})
        prefixes = {k: str(body.get(k) or "")[:1000] for k in model_catalog.PREFIX_KEYS}
        try:
            model_catalog.set_prefix_override(mid, prefixes)
        except model_catalog.CatalogError as e:
            raise HTTPException(400, str(e)) from e
        return {"model": mid, "runtime": _entry(mid).runtime.model_dump(), "active": after_prefix_change(mid)}

    @app.delete("/api/embedding/local/{mid}/prefixes")
    def local_prefixes_reset(mid: str):
        """Präfixe eines Katalogmodells auf die Werte des Katalogs zurücksetzen."""
        _entry(mid)
        try:
            model_catalog.set_prefix_override(mid, None)
        except model_catalog.CatalogError as e:
            raise HTTPException(400, str(e)) from e
        return {"model": mid, "runtime": _entry(mid).runtime.model_dump(), "active": after_prefix_change(mid)}

    @app.delete("/api/embedding/user/{mid}")
    def user_model_delete(mid: str):
        local_delete(mid)
        return {"removed": model_catalog.remove_user_model(mid)}

    # -- Vergleichsmodus ----------------------------------------------------------------------------------
    @app.post("/api/embedding/compare")
    def embedding_compare(body: dict = Body(...)):
        from zotllm.retrieval.compare import compare

        query = (body.get("query") or "").strip()
        if not query:
            raise HTTPException(400, "Suchbegriff fehlt")
        a, b = str(body.get("a") or ""), str(body.get("b") or "")
        if not a or not b or a == b:
            raise HTTPException(400, "Bitte zwei verschiedene Modelle wählen.")
        return compare(engine, query, a, b, body.get("filters") or {}, k=int(body.get("k") or 10))

    # -- Zotero ---------------------------------------------------------------------------------
    @app.get("/api/zotero/status")
    def zotero_status():
        return engine.zotero().status()

    @app.post("/api/zotero/authorize")
    def zotero_authorize():
        from zotllm.winfocus import start_dialog_watch

        # Zotero öffnet den Bestätigungsdialog gern hinter anderen Fenstern – nach vorne holen
        stop = start_dialog_watch()
        try:
            ok = engine.zotero().authorize()
        finally:
            stop.set()
        return {"authorized": ok}

    @app.delete("/api/zotero/authorize")
    def zotero_revoke():
        engine.zotero().revoke_local()
        return {"revoked": True}

    @app.get("/api/zotero/tree")
    def zotero_tree():
        """Abbild aller Bibliotheken (eigene + Gruppen) mit Sammlungen und Untersammlungen."""
        return fetch_tree(engine)

    @app.get("/api/zotero/describe")
    def zotero_describe(sources: str = ""):
        """Namen und Pfade zu Quellen wie 'users/0:ABCD1234' (für Aufrufe aus dem Zotero-Plugin)."""
        return {"sources": describe_sources(engine, [s for s in sources.split(",") if ":" in s])}

    # -- Wissenskorpora ------------------------------------------------------------------------------
    def corpus_view(c: dict, space: str | None) -> dict:
        scope = indexer.scope(corpus_id=c["id"])
        libs = engine.libraries_of(c["sources"])
        synced = all(engine.store.library_state(lib).get("synced_at") for lib in libs) if libs else False
        stats = engine.store.scope_stats(scope, space)
        # Wann zuletzt Texte dieses Korpus gelesen oder eingebettet wurden (Vorauswahl rechts in der Ansicht Index):
        # Verlauf der Läufe (auch reines Einbetten), sonst das Lesedatum der Texte
        activity = engine.store.recent_activity()
        times = [t for k, t in activity.items() if k in scope] + [stats.get("last_read_at")]
        last = max((t for t in times if t), default=None)
        return {**c, "sources_info": describe_sources(engine, c["sources"]), "libraries": libs, "synced": synced,
                "project_ids": engine.store.corpus_project_ids(c["id"]), "last_indexed_at": last, "stats": stats}

    def _corpus(cid: int) -> dict:
        c = engine.store.corpus(cid)
        if not c:
            raise HTTPException(404, "Wissenskorpus nicht gefunden")
        return c

    def _check_corpus(body: dict, own_id: int | None = None) -> None:
        name = (body.get("name") or "").strip() if "name" in body else None
        if name is not None:
            if not name:
                raise HTTPException(400, "Bitte einen Namen für den Wissenskorpus angeben.")
            for other in engine.store.corpora():
                if other["name"].casefold() == name.casefold() and other["id"] != own_id:
                    raise HTTPException(409, f"Es gibt bereits einen Wissenskorpus „{other['name']}“.")
        sources = body.get("sources")
        if sources is not None and (not isinstance(sources, list) or not all(
                isinstance(s, str) and ":" in s for s in sources)):
            raise HTTPException(400, "Ungültige Quellen")

    @app.get("/api/corpora")
    def corpora_list():
        space = engine.embedding_status().get("space")
        return {"corpora": [corpus_view(c, space) for c in engine.store.corpora()]}

    @app.post("/api/corpora")
    def corpus_create(body: dict = Body(...)):
        _check_corpus({"name": body.get("name", ""), **body})
        cid = engine.store.create_corpus(body["name"], body.get("sources") or [], body.get("description") or "")
        if body.get("project_id"):
            engine.store.assign_corpus(int(body["project_id"]), cid)
        return corpus_view(_corpus(cid), engine.embedding_status().get("space"))

    @app.put("/api/corpora/{cid}")
    def corpus_update(cid: int, body: dict = Body(...)):
        _corpus(cid)
        _check_corpus(body, own_id=cid)
        engine.store.update_corpus(cid, name=body.get("name"), description=body.get("description"),
                                   sources=body.get("sources"))
        return corpus_view(_corpus(cid), engine.embedding_status().get("space"))

    @app.delete("/api/corpora/{cid}")
    def corpus_delete(cid: int):
        _corpus(cid)
        engine.store.delete_corpus(cid)
        return {"deleted": cid}

    @app.post("/api/corpora/preview")
    def corpus_preview(body: dict = Body(...)):
        """Kennzahlen für eine (noch nicht gespeicherte) Auswahl – z. B. wie viele Texte zu indexieren sind."""
        sources = [s for s in body.get("sources") or [] if isinstance(s, str) and ":" in s]
        scope = indexer.scope(collections=sources) if sources else set()
        libs = engine.libraries_of(sources)
        unsynced = [lib for lib in libs if not engine.store.library_state(lib).get("synced_at")]
        return {"stats": engine.store.scope_stats(scope, engine.embedding_status().get("space")), "unsynced": unsynced}

    @app.post("/api/corpora/{cid}/items")
    def corpus_add_items(cid: int, body: dict = Body(...)):
        """Einzelne Einträge (aus der Suche) in einen Korpus aufnehmen bzw. entfernen."""
        c = _corpus(cid)
        keys = [f"{x['lib']}:@{x['key']}" for x in body.get("items") or [] if x.get("lib") and x.get("key")]
        sources = set(c["sources"])
        if body.get("remove"):
            sources -= set(keys)
        else:
            sources |= set(keys)
        engine.store.update_corpus(cid, sources=sorted(sources))
        return corpus_view(_corpus(cid), engine.embedding_status().get("space"))

    @app.get("/api/corpora/{cid}/documents")
    def corpus_documents(cid: int):
        """Texte eines Korpus nach Status: indexiert, offen, Probleme (für das Panel in „Index“)."""
        from zotllm.rag.sources import author_year

        _corpus(cid)
        raw = indexer.scope(corpus_id=cid, resolve=False)
        scope = engine.resolve_copies(raw)
        rows = engine.store.con.execute(
            "SELECT lib, key, parent, title, content_type, status, error, n_pages, n_chunks, indexed_at FROM attachments"
            " WHERE status NOT IN ('skipped','redundant')").fetchall()
        rows = [dict(r) for r in rows if (r["lib"], r["parent"]) in scope]
        items = engine.store.items({(r["lib"], r["parent"]) for r in rows})
        # Dublette, deren gewählte Kopie in einer anderen Bibliothek liegt: dort wird der Text gelesen
        lib_names = {"users/0": "Meine Bibliothek", **engine.store.library_names()}
        emb = engine.embedding_status()
        # „Indexiert“ heisst durchsuchbar mit dem aktiven Modell: gelesene Texte mit fehlenden Vektoren sind einzubetten
        coverage = engine.store.chunk_coverage(emb.get("space"))
        groups: dict = {"indexed": [], "to_embed": [], "refresh": [], "pending": [], "problems": []}
        for r in rows:
            it = items.get((r["lib"], r["parent"])) or {}
            entry = {"lib": r["lib"], "item_key": r["parent"], "att_key": r["key"],
                     "title": it.get("title") or r["title"] or r["key"], "citation": tr(author_year(it)) if it else "",
                     "creators": strip_bidi(it.get("creator_summary") or ""), "year": it.get("year"),
                     "pages": r["n_pages"], "chunks": r["n_chunks"], "status": r["status"], "error": r["error"],
                     "select": zotero_select_url(r["lib"], r["parent"]),
                     "pdf": zotero_open_pdf_url(r["lib"], r["key"])
                     if r["status"] == "indexed" and opens_in_reader(r.get("content_type")) else None,
                     "missing": (coverage.get((r["lib"], r["key"])) or (0, 0))[1],
                     "copy_from": tr_exact(lib_names.get(r["lib"], r["lib"])) if (r["lib"], r["parent"]) not in raw
                     else None}
            state = engine.store.doc_state(r["status"], coverage.get((r["lib"], r["key"])))
            groups[state if state in groups else "problems"].append(entry)
        for lst in groups.values():
            lst.sort(key=lambda e: (e["creators"].casefold(), e["year"] or 0, e["title"].casefold()))
        return {**groups, "model": emb.get("label")}

    # -- Suche in der Zotero-Bibliothek (ohne Sprachmodell) ------------------------------------------------
    @app.post("/api/library/search")
    def library_search(body: dict = Body(default={})):
        from zotllm.library_search import CatalogQuery, remember_search, search_catalog

        query = CatalogQuery.from_dict(body.get("query") or body)
        result = search_catalog(engine.store, query)
        # In welchen Korpora des Projekts steckt jeder Treffer?
        pid = body.get("project_id")
        if pid and result["results"]:
            # Mitgliedschaft wie in den Sammlungen (ohne Abbildung von Dubletten auf die gewählte Kopie)
            scopes = {cid: indexer.scope(corpus_id=cid, resolve=False) for cid in engine.store.project_corpus_ids(int(pid))}
            for r in result["results"]:
                r["corpora"] = [cid for cid, sc in scopes.items() if (r["lib"], r["key"]) in sc]
        # Neue Suche (nicht „Weitere laden“) in den Suchverlauf des Projekts
        if pid and query.offset == 0 and body.get("remember", True):
            result["search_id"] = remember_search(engine.store, int(pid), query, result["total"])
            result["searches"] = engine.store.searches(int(pid))
        return result

    @app.get("/api/library/searches")
    def library_searches(project: int):
        return {"searches": engine.store.searches(project)}

    # -- Auswahl aus der Suche: Literaturnachweise, Export, Zotero-Sammlung ---------------------------------
    def _selection(body: dict) -> list[tuple[str, str]]:
        keys = list(dict.fromkeys((str(x.get("lib") or ""), str(x.get("key") or ""))
                                  for x in body.get("items") or [] if isinstance(x, dict)))
        known = engine.store.items(keys)
        keys = [k for k in keys if k in known]
        if not keys:
            raise HTTPException(400, "Keine Einträge ausgewählt.")
        if len(keys) > 2000:
            raise HTTPException(400, "Höchstens 2000 Einträge auf einmal.")
        return keys

    @app.post("/api/library/cite")
    def library_cite(body: dict = Body(...)):
        """Literaturliste und Kurzbelege der Auswahl im eingestellten Zitierstil (zum Kopieren)."""
        from zotllm import exporting

        return exporting.selection_citations(engine, _selection(body))

    selection_files: dict[str, tuple[float, str, Any, str]] = {}

    @app.post("/api/library/export")
    def library_export(body: dict = Body(...)):
        """Auswahl als BibTeX, RIS, Word (Zotero-Felder) oder Markdown vorbereiten; abholen über den Token (GET,
        so kann das Programmfenster die Datei mit dem Speichern-Dialog sichern)."""
        from zotllm import exporting

        name, content, media = exporting.build_selection(engine, _selection(body), str(body.get("format") or ""))
        now = time.time()
        for token in [t for t, v in selection_files.items() if now - v[0] > 600]:
            selection_files.pop(token, None)
        token = secrets.token_urlsafe(16)
        selection_files[token] = (now, name, content, media)
        return {"token": token, "filename": name}

    @app.get("/api/library/export/{token}")
    def library_export_file(token: str):
        from urllib.parse import quote

        entry = selection_files.pop(token, None)
        if not entry:
            raise HTTPException(404, "Der Export ist abgelaufen – bitte erneut speichern.")
        _, name, content, media = entry
        return Response(content, media_type=media,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.post("/api/library/to-collection")
    def library_to_collection(body: dict = Body(...)):
        """Auswahl in eine Zotero-Sammlung legen (bestehende oder neue; Schreibzugriff nötig). Eine Zotero-Sammlung
        gehört zu einer Bibliothek – Einträge aus anderen Bibliotheken werden übersprungen."""
        keys = _selection(body)
        lib = str(body.get("lib") or "")
        mine = [k for lb, k in keys if lb == lib]
        if not mine:
            raise HTTPException(400, "Keiner der gewählten Einträge liegt in dieser Bibliothek.")
        collection = str(body.get("collection") or "")
        name = str(body.get("new_name") or "").strip()
        zot = engine.zotero()
        if not collection:
            if not name:
                raise HTTPException(400, "Bitte eine Sammlung wählen oder einen Namen für eine neue angeben.")
            collection = zot.create_collection(lib, name, str(body.get("parent") or "") or None)
        added = zot.add_to_collection(lib, collection, mine)
        scheduler.trigger_catalog_check()  # neue Zuordnung bald auch in den Fundorten der Suche
        return {"added": added, "already": len(mine) - added, "skipped": len(keys) - len(mine), "lib": lib,
                "collection": collection, "select": zotero_select_url(lib, mine[0], collection)}

    @app.delete("/api/library/searches")
    def library_searches_forget(project: int, id: int | None = None):
        """Eine Suche aus dem Verlauf des Projekts entfernen (id) oder ohne id den ganzen Verlauf."""
        engine.store.forget_searches(project, id)
        return {"searches": engine.store.searches(project)}

    @app.get("/api/library/status")
    def library_status():
        from zotllm.library_search import facets

        at = engine.store.get_meta("catalog_synced_at")
        job = engine.jobs.running("catalog")
        return {"synced_at": float(at) if at else None, "facets": facets(engine.store),
                "job": job.as_dict() if job else None}

    @app.post("/api/library/sync")
    def library_sync(body: dict = Body(default={})):
        full = bool(body.get("full"))
        return job_or_409("catalog", "Suchkatalog abgleichen", lambda job: indexer.sync_catalog(job, full=full),
                          group="catalog")

    @app.post("/api/client-error")
    def client_error(body: dict = Body(default={})):
        """Darstellungsfehler der Oberfläche ins Protokoll schreiben (zur Fehlersuche)."""
        log.error("Oberfläche: %s – %s\n%s", str(body.get("part"))[:80], str(body.get("message"))[:500],
                  str(body.get("stack"))[:4000])
        return {"ok": True}

    # -- Projekte ---------------------------------------------------------------------------------
    def _project(pid: int) -> dict:
        p = engine.store.project(pid)
        if not p:
            raise HTTPException(404, "Projekt nicht gefunden")
        return p

    def _check_project_name(name: str, own_id: int | None = None) -> str:
        name = (name or "").strip()
        if not name:
            raise HTTPException(400, "Bitte einen Namen für das Projekt angeben.")
        for p in engine.store.projects():
            if p["name"].casefold() == name.casefold() and p["id"] != own_id:
                raise HTTPException(409, f"Es gibt bereits ein Projekt „{p['name']}“.")
        return name

    @app.get("/api/projects")
    def projects_list():
        engine.ensure_project()
        return {"projects": engine.store.projects()}

    @app.post("/api/projects")
    def project_create(body: dict = Body(...)):
        name = _check_project_name(body.get("name", ""))
        pid = engine.store.create_project(name, body.get("description") or "", body.get("color") or "")
        for cid in body.get("corpus_ids") or []:
            engine.store.assign_corpus(pid, int(cid))
        return _project(pid)

    @app.put("/api/projects/{pid}")
    def project_update(pid: int, body: dict = Body(...)):
        _project(pid)
        name = _check_project_name(body["name"], own_id=pid) if "name" in body else None
        extra = {}
        if "embedding" in body:  # eigenes Embedding-Modell des Projekts (None = keins)
            from zotllm.engine import project_embedding

            extra["embedding"] = project_embedding(body["embedding"])
        engine.store.update_project(pid, name=name, description=body.get("description"), color=body.get("color"),
                                    **extra)
        out = _project(pid)
        if extra.get("embedding") and engine.active_project_id() == pid:
            out["embedding_switched"] = engine.apply_project_embedding(pid)
        return out

    @app.post("/api/projects/{pid}/open")
    def project_open(pid: int):
        if _project(pid).get("archived_at"):
            raise HTTPException(400, "Das Projekt ist archiviert. Erst aus dem Archiv holen, dann öffnen.")
        engine.store.update_project(pid, opened_at=time.time())
        # Projekt mit eigenem Embedding-Modell: dieses aktivieren (sein Index bleibt erhalten)
        switched = engine.apply_project_embedding(pid)
        return {**_project(pid), "embedding_switched": switched}

    def _last_active(pid: int) -> bool:
        """Ist dies das einzige nicht archivierte Projekt? (Eines muss immer offen sein.)"""
        return [p["id"] for p in engine.store.projects() if not p.get("archived_at")] == [pid]

    @app.post("/api/projects/reorder")
    def project_reorder(body: dict = Body(...)):
        """Neue Reihenfolge der (offenen) Projekte, z. B. nach Ziehen in der Projektspalte."""
        known = {p["id"] for p in engine.store.projects()}
        ids = [int(x) for x in body.get("ids") or []]
        if not ids or len(set(ids)) != len(ids) or not set(ids) <= known:
            raise HTTPException(400, "Ungültige Reihenfolge")
        engine.store.set_project_order(ids)
        return {"projects": engine.store.projects()}

    @app.post("/api/projects/{pid}/archive")
    def project_archive(pid: int, body: dict = Body(default={})):
        _project(pid)
        archived = bool(body.get("archived", True))
        if archived and _last_active(pid):
            raise HTTPException(400, "Das letzte offene Projekt kann nicht archiviert werden.")
        engine.store.set_project_archived(pid, archived)
        return _project(pid)

    @app.delete("/api/projects/{pid}")
    def project_delete(pid: int, delete_corpora: bool = False):
        p = _project(pid)
        if len(engine.store.projects()) <= 1:
            raise HTTPException(400, "Das letzte Projekt kann nicht gelöscht werden.")
        if _last_active(pid):
            raise HTTPException(400, "Das letzte offene Projekt kann nicht gelöscht werden.")
        exclusive = [cid for cid in p["corpus_ids"] if engine.store.corpus_project_ids(cid) == [pid]]
        engine.store.delete_project(pid)
        if delete_corpora:
            for cid in exclusive:
                engine.store.delete_corpus(cid)
        return {"deleted": pid, "corpora_deleted": len(exclusive) if delete_corpora else 0}

    @app.post("/api/projects/{pid}/duplicate")
    def project_duplicate(pid: int):
        from zotllm.projects_io import export_project, import_project

        _, data = export_project(engine, pid)
        return import_project(engine, data)

    @app.put("/api/projects/{pid}/corpora/{cid}")
    def project_assign(pid: int, cid: int, body: dict = Body(default={})):
        _project(pid)
        _corpus(cid)
        engine.store.assign_corpus(pid, cid, bool(body.get("assigned", True)))
        return _project(pid)

    @app.get("/api/projects/{pid}/export")
    def project_export(pid: int):
        from urllib.parse import quote

        from zotllm.projects_io import export_project

        _project(pid)
        filename, data = export_project(engine, pid)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})

    @app.post("/api/projects/import")
    async def project_import(request: Request):
        from zotllm.projects_io import import_project

        return import_project(engine, await request.body())

    # -- Zitierstile (aus Zotero) -------------------------------------------------------------------
    def _style_analysis(style_id: str, data_dir) -> dict:
        from zotllm.zotero import styles as zstyles

        loc = zstyles.analyze_locator(zstyles.style_xml(style_id, data_dir))
        lang = "de" if engine.settings.language == "de" else "en"
        return {**loc.as_dict(), "preview": zstyles.preview(loc, lang, engine.settings.citation_no_page)}

    @app.get("/api/styles")
    def styles_list(refresh: bool = False):
        """In Zotero installierte Zitierstile (Ordner „styles“ des Zotero-Datenordners) und wie der gewählte Stil
        Seiten setzt – samt Musterbeleg mit und ohne Seitenzahl."""
        from zotllm.zotero import styles as zstyles

        if refresh:
            zstyles._cache.clear()
        data_dir = zstyles.zotero_data_dir(engine.store)
        current = zstyles.normalize_style_id(engine.settings.citation_style)
        return {"data_dir": str(data_dir) if data_dir else None,
                "styles": [s.as_dict() for s in zstyles.installed_styles(data_dir)],
                "current": current, "analysis": _style_analysis(current, data_dir)}

    @app.get("/api/styles/analyze")
    def styles_analyze(id: str):
        from zotllm.zotero import styles as zstyles

        return _style_analysis(zstyles.normalize_style_id(id), zstyles.zotero_data_dir(engine.store))

    # -- CSL-Editor --------------------------------------------------------------------------------
    from zotllm import csl_editor as csl

    csl_state: dict = {}

    def csl_repo() -> csl.Repository:
        if "repo" not in csl_state:
            csl_state["repo"] = csl.Repository()
        return csl_state["repo"]

    def csl_call(fn, *args):
        try:
            return fn(*args)
        except csl.CslError as e:
            raise HTTPException(400, str(e)) from e

    def csl_own(slug: str) -> str:
        try:
            return csl.StyleStore.default().get(slug)
        except (KeyError, csl.CslError) as e:
            raise HTTPException(404, "Stil nicht gefunden") from e

    @app.get("/api/csl/repository")
    def csl_search(q: str = "", format: str = "", field: str = ""):
        """Stilsammlung von zotero.org durchsuchen (Liste nur bei Bedarf geladen, danach zwischengespeichert)."""
        return csl_call(csl_repo().search, q, format, field)

    @app.get("/api/csl/repository/{name}")
    def csl_repository_style(name: str):
        return csl_call(csl_repo().fetch, name)

    @app.get("/api/csl/zotero")
    def csl_zotero_styles():
        from zotllm.zotero import styles as zstyles

        return {"styles": [s.as_dict() for s in zstyles.installed_styles(zstyles.zotero_data_dir(engine.store))]}

    @app.get("/api/csl/zotero/style")
    def csl_zotero_style(id: str):
        """CSL eines in Zotero installierten Stils; bei abhängigen Stilen auch der Elternstil (installiert, als
        verborgener Stil oder von zotero.org)."""
        from zotllm.zotero import styles as zstyles

        data_dir = zstyles.zotero_data_dir(engine.store)
        by_id = {s.id: s for s in zstyles.installed_styles(data_dir)}
        style = by_id.get(zstyles.normalize_style_id(id))
        if not style:
            raise HTTPException(404, "Stil nicht gefunden")
        xml = style.file.read_text(encoding="utf-8")
        parent_xml = None
        if style.parent:
            parent = by_id.get(style.parent)
            hidden = data_dir / "styles" / "hidden" if data_dir else None
            if not parent and hidden and hidden.is_dir():
                parent = next((s for f in hidden.glob("*.csl") if (s := zstyles._info(f)) and s.id == style.parent), None)
            if parent:
                parent_xml = parent.file.read_text(encoding="utf-8")
            elif style.parent.replace("http://", "https://", 1).startswith(csl.REPO_PREFIX):
                parent_xml = csl_call(csl_repo().fetch, style.parent.rstrip("/").rsplit("/", 1)[-1])["xml"]
        return {"xml": xml, "parent_xml": parent_xml, "info": csl_call(csl.info, xml)}

    @app.get("/api/csl/styles")
    def csl_styles():
        return {"styles": csl.StyleStore.default().list()}

    @app.post("/api/csl/styles")
    def csl_create(body: dict = Body(...)):
        """Eigenen Stil anlegen: Kopie eines Stils (bei abhängigen Stilen des Elternstils) mit eigenem Namen und
        eigener Kennung, damit das Original beim Installieren nicht überschrieben wird."""
        base, title, template = csl_call(csl.editable_copy, body.get("xml") or "", body.get("parent_xml"),
                                         (body.get("title") or "").strip() or None)
        slug, xml = csl_call(csl.StyleStore.default().create, base, title, template)
        return {"slug": slug, "xml": xml, "info": csl.info(xml), "versions": []}

    @app.get("/api/csl/styles/{slug}")
    def csl_style(slug: str):
        xml = csl_own(slug)
        return {"slug": slug, "xml": xml, "info": csl_call(csl.info, xml),
                "versions": csl.StyleStore.default().versions(slug)}

    @app.put("/api/csl/styles/{slug}")
    def csl_save(slug: str, body: dict = Body(...)):
        xml = body.get("xml") or ""
        csl_own(slug)
        problems = csl_call(csl.check, xml)
        if problems:
            raise HTTPException(400, " ".join(problems))
        out = csl_call(csl.StyleStore.default().save, slug, xml)
        return {"slug": slug, "xml": out, "info": csl.info(out), "versions": csl.StyleStore.default().versions(slug)}

    @app.get("/api/csl/styles/{slug}/versions/{name}")
    def csl_version(slug: str, name: str):
        try:
            return {"xml": csl.StyleStore.default().version(slug, name)}
        except KeyError as e:
            raise HTTPException(404, "Version nicht gefunden") from e

    @app.delete("/api/csl/styles/{slug}")
    def csl_delete(slug: str):
        csl_own(slug)
        csl.StyleStore.default().delete(slug)
        return {"deleted": slug}

    @app.post("/api/csl/styles/{slug}/install")
    def csl_install(slug: str):
        """In Zotero installieren (über das ZotLLM-Plugin) – danach auch in ZotLLM als Zitierstil wählbar."""
        from zotllm.zotero import PluginMissing
        from zotllm.zotero import styles as zstyles

        xml = csl_own(slug)
        try:
            engine.zotero().install_style(xml)
        except PluginMissing as e:
            raise HTTPException(409, str(e)) from e
        except ZoteroUnavailable as e:
            raise HTTPException(503, str(e)) from e
        except ZoteroError as e:
            raise HTTPException(502, str(e)) from e
        zstyles._cache.clear()
        return {"installed": True, "id": csl.info(xml)["id"]}

    @app.get("/api/csl/item-types")
    def csl_item_types(lang: str = "de"):
        """Weitere Eintragsarten für die Vorschau: Liste, Namen und Feldzuordnung aus Zotero, Beispiele aus ZotLLM."""
        from zotllm import csl_types

        schema, source = csl_types.load_schema(engine.zotero())
        if not schema:
            return {"types": [], "source": ""}
        return {"types": csl_types.sample_types(schema, lang), "source": source}

    @app.post("/api/csl/library-examples")
    def csl_library_examples(body: dict = Body(...)):
        """Beispiele der Vorschau aus der eigenen Bibliothek: je Beispiel der vollständigste passende Eintrag."""
        from zotllm import csl_types
        from zotllm.exporting import Citations

        picks = csl_types.pick_library_items(engine.store, [str(x) for x in (body.get("examples") or [])][:60])
        if not picks:
            return {"items": {}}
        keys = list(dict.fromkeys(picks.values()))
        cites = Citations(engine, keys, engine.settings.citation_style, engine.settings.language)
        out = {}
        for ex, k in picks.items():
            item = dict(cites.csl.get(k) or {})
            if item:
                item["id"] = f"lib:{ex}"
                out[ex] = {"item": item, "ref": f"{k[0]}:{k[1]}", "title": (cites.items.get(k) or {}).get("title", "")}
        return {"items": out}

    @app.post("/api/csl/collection-examples")
    def csl_collection_examples(body: dict = Body(...)):
        """Einträge einer Sammlung (mit Untersammlungen) als Beispiele der Vorschau: nach Eintragsart und Titel, höchstens 40."""
        from zotllm import csl_types
        from zotllm.exporting import Citations

        source = str(body.get("collection") or "")
        if ":" not in source or source.endswith(":*"):
            raise HTTPException(400, "Bitte eine Sammlung wählen.")
        items = engine.store.items(indexer.scope(collections=[source], resolve=False))
        keys = sorted(items, key=lambda k: (items[k].get("item_type") or "", (items[k].get("title") or "").casefold()))
        if not keys:
            return {"items": [], "total": 0}
        names = csl_types.type_names(csl_types.load_schema(engine.zotero())[0], body.get("lang") or "de")
        cites = Citations(engine, keys[:40], engine.settings.citation_style, engine.settings.language)
        out = []
        for k in keys[:40]:
            item = dict(cites.csl.get(k) or {})
            if item:
                item["id"] = f"c:{k[0]}:{k[1]}"
                itype = items[k].get("item_type") or ""
                out.append({"ref": f"{k[0]}:{k[1]}", "label": names.get(itype) or itype, "title": items[k].get("title") or "",
                            "item": item})
        return {"items": out, "total": len(keys)}

    @app.post("/api/csl/items")
    def csl_items(body: dict = Body(...)):
        """Eigene Zotero-Einträge als CSL-JSON für die Vorschau (aus Zotero, sonst aus den gespeicherten Angaben)."""
        from zotllm.exporting import Citations

        keys = []
        for ref in (body.get("items") or [])[:20]:
            lib, _, key = str(ref).partition(":")
            if lib and key:
                keys.append((lib, key))
        if not keys:
            return {"items": []}
        cites = Citations(engine, keys, engine.settings.citation_style, engine.settings.language)
        out = []
        for k in keys:
            item = dict(cites.csl.get(k) or {})
            if item:
                item["id"] = f"{k[0]}:{k[1]}"
                out.append(item)
        return {"items": out}

    # -- Presets -----------------------------------------------------------------------------------
    @app.get("/api/presets")
    def presets_list():
        from zotllm import presets

        s = engine.settings
        items = presets.all_presets(s)
        active = items.get(s.active_preset)
        return {"presets": [{"id": k, **v} for k, v in items.items()], "active": s.active_preset,
                "changed": presets.differences(s, active["values"]) if active else [],
                "current": presets.current_values(s)}

    @app.post("/api/presets/apply")
    def presets_apply(body: dict = Body(...)):
        from zotllm import presets

        items = presets.all_presets(engine.settings)
        key = body.get("id")
        if key not in items:
            raise HTTPException(404, "Preset nicht gefunden")
        engine.settings_store.update({**presets.patch_for(items[key]["values"]), "active_preset": key})
        return presets_list()

    @app.post("/api/presets")
    def presets_save(body: dict = Body(...)):
        """Aktuelle Werte (oder übergebene) als eigenes Preset speichern bzw. importieren."""
        from zotllm import presets

        label = (body.get("label") or "").strip()
        if not label:
            raise HTTPException(400, "Bitte einen Namen für das Preset angeben.")
        key = presets.slug(label)
        if key in presets.BUILTIN:
            key = f"eigen-{key}"
        values = body.get("values") or presets.current_values(engine.settings)
        values = {f: v for f, v in values.items() if f in presets.FIELDS}
        # Werte prüfen, indem sie probeweise auf die Einstellungen angewendet werden
        try:
            engine.settings.model_validate({**engine.settings.model_dump(), **{
                sec: {**getattr(engine.settings, sec).model_dump(), **vals}
                for sec, vals in presets.patch_for(values).items()}})
        except ValidationError as e:
            raise HTTPException(400, "Ungültige Werte im Preset") from e
        user = dict(engine.settings.presets)
        user[key] = {"label": label, "description": body.get("description") or "", "values": values}
        engine.settings_store.update({"presets": user, **({"active_preset": key} if body.get("activate", True)
                                                           else {})})
        return presets_list()

    @app.delete("/api/presets/{key}")
    def presets_delete(key: str):
        user = dict(engine.settings.presets)
        if key not in user:
            raise HTTPException(404, "Nur eigene Presets können gelöscht werden.")
        del user[key]
        patch: dict = {"presets": user}
        if engine.settings.active_preset == key:
            patch["active_preset"] = "ausgewogen"
        engine.settings_store.update(patch)
        return presets_list()

    @app.post("/api/corpora/{cid}/index")
    def corpus_index(cid: int, body: dict = Body(default={})):
        c = _corpus(cid)
        if not c["sources"]:
            raise HTTPException(400, "Der Wissenskorpus enthält noch keine Sammlungen.")
        params = {"sync": True, "corpus_id": cid, "retry_errors": bool(body.get("retry_errors")),
                  "full_sync": bool(body.get("full_sync"))}
        return submit_index(f"Indexierung: {c['name']}", params)

    # -- Warteschlange der Indexierläufe -----------------------------------------------------------
    def submit_index(title: str, params: dict) -> dict:
        """Indexierlauf starten – läuft schon einer, kommt er in die Warteschlange (Antwort mit "queued")."""
        kind = ("embed" if params.get("embed_only") else "retry" if params.get("retry_errors")
                else "full_sync" if params.get("full_sync") else "collections" if params.get("collections")
                else "items" if params.get("items") else "index")
        info = {"key": json.dumps(params, sort_keys=True, default=str), "kind": kind,
                "corpus_id": params.get("corpus_id"), "collections": len(params.get("collections") or []),
                "items": len(params.get("items") or [])}
        r = engine.index_queue.submit(title, lambda job: indexer.run(job, **params), info)
        if "job" in r:
            return r["job"].as_dict()
        return {"queued": True, "entry": queue_list([r["entry"]])[0], "position": r["position"],
                "duplicate": r["duplicate"]}

    def queue_list(entries: list[dict] | None = None) -> list[dict]:
        """Wartende Läufe mit Korpus und Projekten (Namen von jetzt – sie können sich seit der Aufnahme ändern)."""
        entries = engine.index_queue.entries() if entries is None else entries
        if not entries:
            return []
        corpora = {c["id"]: c for c in engine.store.corpora()}
        projects = engine.store.projects()
        out = []
        for e in entries:
            cid = int(e["corpus_id"]) if e.get("corpus_id") else None
            out.append({"id": e["id"], "title": tr(e["title"]), "kind": e["kind"], "queued_at": e["queued_at"],
                        "corpus_id": cid, "corpus": corpora[cid]["name"] if cid in corpora else None,
                        "projects": [p["name"] for p in projects if cid and cid in p["corpus_ids"]],
                        "collections": e.get("collections", 0), "items": e.get("items", 0)})
        return out

    @app.get("/api/index/queue")
    def index_queue():
        return {"queue": queue_list()}

    @app.post("/api/index/queue/{qid}/move")
    def index_queue_move(qid: int, body: dict = Body(...)):
        if not engine.index_queue.move(qid, -1 if int(body.get("delta") or 0) < 0 else 1):
            raise HTTPException(404, "Dieser Auftrag wartet nicht mehr (schon gestartet oder entfernt).")
        return {"queue": queue_list()}

    @app.delete("/api/index/queue/{qid}")
    def index_queue_remove(qid: int):
        if not engine.index_queue.remove(qid):
            raise HTTPException(404, "Dieser Auftrag wartet nicht mehr (schon gestartet oder entfernt).")
        return {"queue": queue_list()}

    # -- Dubletten (dasselbe Werk mehrfach in Zotero, index/duplicates.py) ----------------------------
    def library_list() -> list[dict]:
        names = {"users/0": "Meine Bibliothek", **engine.store.library_names()}
        order = sorted(names, key=lambda lib: (lib != "users/0", names[lib].casefold()))
        return [{"lib": lib, "name": tr_exact(names[lib])} for lib in order]

    @app.get("/api/duplicates")
    def duplicates_list(corpus_id: int | None = None, undecided: bool = False, sync: bool = False):
        """Dubletten in allen Korpora bzw. einem Korpus. undecided: nur Werke ohne Entscheidung (Rückfrage vor
        einem Lauf). sync: Bibliotheken, die noch nie abgeglichen wurden, vorher abgleichen – sonst fehlen ihre
        Einträge (nicht während einer Indexierung oder eines Abgleichs)."""
        if sync and not engine.jobs.running("index") and not engine.jobs.running("catalog"):
            libs = engine.libraries_of(engine.corpus_sources(corpus_id))
            unsynced = [lib for lib in libs if not engine.store.library_state(lib).get("synced_at")]
            if unsynced:
                try:
                    indexer.sync_metadata(libraries=unsynced)
                except ZoteroError as e:  # Zotero nicht erreichbar: dann entscheidet beim Lauf die Regel
                    log.info("Dubletten: Abgleich vorab nicht möglich: %s", e)
        icfg = engine.settings.indexing
        raw = indexer.scope(corpus_id=corpus_id, resolve=False)
        works = duplicates.works_touching(engine.store, raw)
        if undecided:
            known = engine.store.duplicate_choices()
            works = [w for w in works if w not in known]
        groups = duplicates.describe(engine.store, icfg.duplicate_library, works)
        for g in groups:
            for c in g["copies"]:
                c["library"] = tr_exact(c["library"])
        return {"groups": groups, "ask": icfg.ask_duplicates, "preferred": icfg.duplicate_library,
                "libraries": library_list()}

    @app.post("/api/duplicates/choices")
    def duplicates_choose(body: dict = Body(...)):
        """Entscheidungen speichern: [{work, mode: user|rule|separate|null, lib, key}] (user: gewählte Kopie)."""
        groups = engine.store.duplicate_groups()
        todo = []
        for c in body.get("choices") or []:
            work, mode = str(c.get("work") or ""), c.get("mode")
            key = (str(c.get("lib") or ""), str(c.get("key") or ""))
            if work not in groups or mode not in ("user", "rule", "separate", None) or (
                    mode == "user" and key not in groups[work]):
                raise HTTPException(400, "Ungültige Auswahl – die Dubletten haben sich inzwischen geändert.")
            todo.append((work, mode, key))
        for work, mode, key in todo:
            engine.store.set_duplicate_choice(work, mode, *key)
        return {"saved": len(todo)}

    # -- Index ------------------------------------------------------------------------------------
    def scope_info() -> dict:
        scope = indexer.scope()
        return {"pending_in_scope": engine.store.count_pending(scope) if scope else 0, "scope_empty": not scope}

    @app.get("/api/index/stats")
    def index_stats():
        emb = engine.embedding_status()
        libs = engine.libraries_of(engine.corpus_sources())
        return {"stats": {**engine.store.stats(emb.get("space")), **scope_info()}, "embedding": emb,
                "libraries": [engine.store.library_state(lib) for lib in libs]}

    @app.get("/api/index/overview")
    def index_overview():
        """Zustand des Index über alle Korpora: Texte, indexiert, offen, Probleme; letzte und nächste Prüfung."""
        corpora = engine.store.corpora()
        emb = engine.embedding_status()
        # Während eines Laufs dieselben (höchstens 5 s alten) Zahlen wie die Statusleiste, sonst frisch
        stats = index_coverage(emb.get("space"), force=not engine.jobs.running("index")) if corpora else None
        checked = engine.store.get_meta("index_checked_at")
        icfg = engine.settings.indexing
        return {"corpora": len(corpora), "stats": stats, "checked_at": float(checked) if checked else None,
                "model": {"label": emb.get("label"), "provider": emb.get("provider"), "ok": bool(emb.get("ok")),
                          "space": emb.get("space")},
                "embed_estimate": embed_estimate(stats["to_embed_chunks"]) if stats and emb.get("ok") else None,
                "mode": icfg.mode, "next_check_at": scheduler.next_run_at(), "zotero_running": scheduler.zotero_running,
                "window": [icfg.background_from_hour, icfg.background_to_hour]
                if icfg.background_from_hour is not None and icfg.background_to_hour is not None else None}

    @app.get("/api/index/runs")
    def index_runs(limit: int = 10):
        runs = engine.store.index_runs(max(1, min(limit, 30)))
        return {"runs": [tr_fields(r, "title", "stopped", "error") for r in runs]}

    @app.get("/api/index/runs/{run_id}")
    def index_run(run_id: int):
        r = engine.store.index_run(run_id)
        if not r:
            raise HTTPException(404, "Nicht gefunden")
        for d in r["docs"]:
            d["select"] = zotero_select_url(d["lib"], d["parent"])
            d["message"] = tr(d.get("message") or "")
        return tr_fields(r, "title", "stopped", "error")

    @app.post("/api/index/runs/{run_id}/dismiss")
    def index_run_dismiss(run_id: int):
        engine.store.dismiss_index_run(run_id)
        return {"dismissed": run_id}

    @app.get("/api/index/errors")
    def index_errors():
        return {"errors": engine.store.errors()}

    @app.get("/api/index/backups")
    def index_backups():
        folder = indexer.backup_dir()
        files = sorted(folder.glob("index-*.sqlite3"), reverse=True) if folder.exists() else []
        return {"folder": str(folder), "backups": [{"name": f.name, "bytes": f.stat().st_size,
                                                     "created_at": f.stat().st_mtime} for f in files]}

    @app.post("/api/index/backup")
    def index_backup():
        if engine.jobs.running("index"):
            raise HTTPException(409, "Während einer Indexierung wird am Ende automatisch gesichert.")
        path = indexer.maybe_backup(force=True)
        if path is None:
            raise HTTPException(500, "Sicherung fehlgeschlagen – Details im Protokoll.")
        return index_backups()

    @app.post("/api/index/run")
    def index_run(body: dict = Body(default={})):
        params = {
            "sync": bool(body.get("sync", True)),
            "collections": body.get("collections"),
            "items": body.get("items"),
            "retry_errors": bool(body.get("retry_errors", False)),
            "full_sync": bool(body.get("full_sync", False)),
            "corpus_id": body.get("corpus_id"),
            # Nur einbetten (z. B. nach einem Modellwechsel): gelesene Texte bekommen Vektoren, nichts wird neu gelesen
            "embed_only": bool(body.get("embed_only", False)),
        }
        if params["embed_only"]:
            params["sync"] = False
        title = "Indexierung aller Korpora"
        if params["corpus_id"]:
            title = f"Indexierung: {_corpus(int(params['corpus_id']))['name']}"
        elif params["collections"]:
            title = f"Indexierung ({len(params['collections'])} Sammlung(en))"
        elif params["items"]:
            title = f"Indexierung ({len(params['items'])} Einträge)"
        return submit_index(title, params)

    # -- Aufträge ---------------------------------------------------------------------------------
    @app.get("/api/jobs")
    def jobs():
        return {"jobs": engine.jobs.list()}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: int):
        j = engine.jobs.get(job_id)
        if not j:
            raise HTTPException(404, "Auftrag nicht gefunden")
        return j.as_dict()

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: int):
        return {"cancelled": engine.jobs.cancel(job_id)}

    # -- Suche & Chat -------------------------------------------------------------------------------
    @app.post("/api/search")
    def search(body: dict = Body(...)):
        query = (body.get("query") or "").strip()
        if not query:
            raise HTTPException(400, "Suchbegriff fehlt")
        cfg = engine.settings.retrieval
        k = int(body.get("k") or cfg.top_k)
        hits = Searcher(engine).search(query, engine.make_filter(body.get("filters")), cfg, k=k)
        return {"sources": [s.as_dict() for s in build_sources(engine.store, hits, 0, 10**9)]}

    @app.post("/api/chat")
    def chat_stream(body: dict = Body(...)):
        question = (body.get("question") or "").strip()
        if not question:
            raise HTTPException(400, "Frage fehlt")
        opts = AskOptions(
            filters=body.get("filters") or {}, retrieval=body.get("retrieval") or {},
            provider=body.get("provider"), model=body.get("model"), search_only=bool(body.get("search_only")),
            project_id=body.get("project_id"),
        )

        def localized(ev: dict) -> dict:
            if ev.get("type") in ("status", "warning"):
                return tr_fields(ev, "text", "missing")
            if ev.get("type") == "error":
                return tr_fields(ev, "message")
            if ev.get("type") == "delta":
                return {**ev, "text": tr_exact(ev.get("text"))}  # nur feste Meldungen, nie Text des Modells
            return ev

        def events():
            try:
                for ev in chat.ask(question, body.get("chat_id"), opts):
                    yield f"data: {json.dumps(localized(ev), ensure_ascii=False)}\n\n"
            except Exception as e:  # noqa: BLE001
                log.exception("Chat-Fehler")
                yield f"data: {json.dumps({'type': 'error', 'message': tr(str(e))}, ensure_ascii=False)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/chats")
    def chats(project: int | None = None):
        return {"chats": engine.store.chats(project_id=project)}

    @app.put("/api/chats/{chat_id}")
    def chat_rename(chat_id: int, body: dict = Body(...)):
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "Titel fehlt")
        engine.store.rename_chat(chat_id, title)
        return engine.store.chat(chat_id)

    @app.get("/api/chats/{chat_id}")
    def chat_get(chat_id: int):
        return {"messages": engine.store.chat_messages(chat_id)}

    @app.delete("/api/chats/{chat_id}")
    def chat_delete(chat_id: int):
        engine.store.delete_chat(chat_id)
        return {"deleted": chat_id}

    # -- Forschungsstand ----------------------------------------------------------------------------
    @app.get("/api/reviews")
    def review_list(project: int | None = None):
        return {"reviews": engine.store.reviews(project_id=project)}

    @app.post("/api/reviews")
    def review_create(body: dict = Body(...)):
        question = (body.get("question") or "").strip()
        if not question:
            raise HTTPException(400, "Forschungsfrage fehlt")
        rid = reviews.create(body.get("title") or "", question, body.get("filters") or {},
                             body.get("language") or "de", body.get("target_words"), body.get("project_id"))
        return reviews.get(rid)

    @app.put("/api/reviews/{rid}")
    def review_update(rid: int, body: dict = Body(...)):
        _review(rid)
        if "title" in body:
            reviews.set_title(rid, body["title"])
        if "filters" in body or "target_words" in body or "language" in body:
            state = engine.store.get_review(rid)["state"]
            for k in ("filters", "target_words", "language"):
                if k in body:
                    state[k] = body[k]
            engine.store.update_review_state(rid, state)
        return _review(rid)

    @app.post("/api/reviews/{rid}/strategy")
    def review_strategy(rid: int):
        _review(rid)
        return job_or_409("review", "Forschungsstand: Suchstrategie", lambda job: reviews.generate_strategy(job, rid),
                          group="review")

    @app.put("/api/reviews/{rid}/strategy")
    def review_set_strategy(rid: int, body: dict = Body(...)):
        _review(rid)
        reviews.set_strategy(rid, body.get("queries"))
        return _review(rid)

    def _review(rid: int) -> dict:
        try:
            return reviews.get(rid)
        except KeyError as e:
            raise HTTPException(404, "Forschungsstand nicht gefunden") from e

    @app.get("/api/reviews/{rid}")
    def review_get(rid: int):
        return _review(rid)

    @app.delete("/api/reviews/{rid}")
    def review_delete(rid: int):
        engine.store.delete_review(rid)
        return {"deleted": rid}

    @app.post("/api/reviews/{rid}/candidates")
    def review_candidates(rid: int):
        _review(rid)
        return job_or_409("review", "Forschungsstand: Texte finden", lambda job: reviews.find_candidates(job, rid),
                          group="review")

    @app.post("/api/reviews/{rid}/docs")
    def review_doc(rid: int, body: dict = Body(...)):
        engine.store.set_review_doc_included(rid, body["lib"], body["item_key"], bool(body.get("included")))
        return {"ok": True}

    @app.post("/api/reviews/{rid}/collection/export")
    def review_export_collection(rid: int):
        return reviews.export_collection(rid)

    @app.post("/api/reviews/{rid}/collection/import")
    def review_import_collection(rid: int):
        return reviews.import_collection(rid)

    @app.post("/api/reviews/{rid}/confirm")
    def review_confirm(rid: int):
        reviews.confirm(rid)
        return _review(rid)

    @app.get("/api/reviews/{rid}/estimate")
    def review_estimate(rid: int):
        return reviews.estimate_extraction(rid)

    @app.post("/api/reviews/{rid}/extract")
    def review_extract(rid: int):
        _review(rid)
        return job_or_409("review", "Forschungsstand: Auswertungsblätter", lambda job: reviews.extract(job, rid),
                          group="review")

    @app.get("/api/sheets")
    def sheet_get(lib: str, key: str):
        sheet = reviews.sheet_view(lib, key)
        if sheet is None:
            raise HTTPException(404, "Kein Auswertungsblatt für diesen Text")
        return sheet

    @app.post("/api/reviews/{rid}/sheets/rebuild")
    def review_rebuild_sheet(rid: int, body: dict = Body(...)):
        _review(rid)
        lib, key = body["lib"], body["item_key"]
        return job_or_409("review", "Forschungsstand: Auswertungsblatt neu erstellen",
                          lambda job: reviews.rebuild_sheet(job, rid, lib, key), group="review")

    @app.post("/api/reviews/{rid}/outline")
    def review_outline(rid: int):
        _review(rid)
        return job_or_409("review", "Forschungsstand: Gliederung", lambda job: reviews.outline(job, rid),
                          group="review")

    @app.put("/api/reviews/{rid}/outline")
    def review_set_outline(rid: int, body: dict = Body(...)):
        reviews.set_outline(rid, body.get("outline"))
        return _review(rid)

    @app.post("/api/reviews/{rid}/write")
    def review_write(rid: int):
        _review(rid)
        return job_or_409("review", "Forschungsstand: Schreiben", lambda job: reviews.write(job, rid),
                          group="review")

    @app.post("/api/reviews/{rid}/sections/{index}/rewrite")
    def review_rewrite_section(rid: int, index: int):
        r = _review(rid)
        if not 0 <= index < len((r.get("state") or {}).get("sections") or []):
            raise HTTPException(404, "Abschnitt nicht gefunden")
        return job_or_409("review", "Forschungsstand: Abschnitt neu schreiben",
                          lambda job: reviews.rewrite_section(job, rid, index), group="review")

    @app.post("/api/reviews/{rid}/shorten")
    def review_shorten(rid: int, body: dict = Body(default={})):
        """Zu lange Abschnitte kürzen: {"sections": [i, …]} oder ohne Angabe alle, die über dem Plan liegen."""
        r = _review(rid)
        indexes = body.get("sections")
        if indexes is not None and (not isinstance(indexes, list) or not all(isinstance(i, int) for i in indexes)):
            raise HTTPException(400, "Ungültige Abschnitte")
        if not (indexes or reviews.long_sections(r.get("state") or {})):
            raise HTTPException(400, "Kein Abschnitt ist länger als geplant.")
        return job_or_409("review", "Forschungsstand: Abschnitte kürzen",
                          lambda job: reviews.shorten(job, rid, indexes), group="review")

    @app.post("/api/reviews/{rid}/check")
    def review_check(rid: int):
        return reviews.check(rid)

    @app.get("/api/reviews/{rid}/text")
    def review_text(rid: int):
        """Text des Forschungsstands mit aufgelösten Belegen. Ein Klick auf einen Beleg (#cite-N) öffnet in der
        Oberfläche eine Auswahl: Eintrag in Zotero zeigen oder PDF an der Fundstelle öffnen."""
        _review(rid)
        cites: list[dict] = []
        markdown = reviews.render(rid, with_links=True, body_only=True, link_target="dialog", cites=cites)
        return {"markdown": markdown, "citations": cites}

    @app.get("/api/cite")
    def cite(lib: str, key: str, page: str = "", kind: str = "text"):
        """Kurzbeleg und Literaturangabe einer Textstelle im eingestellten Zitierstil (Kopieren einer Textstelle)."""
        from zotllm import exporting

        if not engine.store.item(lib, key):
            raise HTTPException(404, "Nicht gefunden")
        return exporting.source_reference(engine, lib, key, page, kind)

    @app.get("/api/export")
    def export(kind: str, id: int, format: str = "text"):  # noqa: A002
        """Antwort, Textstellen oder Forschungsstand als Text/HTML (Kopieren), Markdown, LaTeX oder Word
        mit Zotero-Belegen und Literaturverzeichnis."""
        from urllib.parse import quote

        from zotllm import exporting

        try:
            name, content, media = exporting.build(engine, kind, id, format)
        except KeyError:
            raise HTTPException(404, "Nicht gefunden") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if format == "text":
            return content
        return Response(content, media_type=media,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.get("/api/reviews/{rid}/export")
    def review_export(rid: int, links: bool = True):
        md = reviews.render(rid, with_links=links)
        return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="forschungsstand-{rid}.md"'})

    @app.post("/api/reviews/{rid}/save-to-zotero")
    def review_save(rid: int):
        return {"note_key": reviews.save_to_zotero(rid)}

    @app.post("/api/sheets/build")
    def sheets_build(body: dict = Body(default={})):
        f = SearchFilter(collections=body.get("collections") or [], item_keys=body.get("items") or [])
        allowed = engine.store.allowed_items(f)
        if allowed is None:
            allowed = {(r["lib"], r["key"]) for r in engine.store.con.execute("SELECT lib, key FROM items")}
        docs = sorted(k for k in allowed if engine.store.document_chunks(k[0], k[1]))
        model_choice = body.get("model") or "helper"
        return job_or_409("sheets", f"Auswertungsblätter für {len(docs)} Texte",
                          lambda job: reviews.build_sheets(job, docs, model_choice=model_choice), group="review")

    # -- Plugin -----------------------------------------------------------------------------------------
    @app.get("/plugin/zotllm.xpi", include_in_schema=False)
    def plugin_xpi(request: Request):
        from zotllm.plugin_build import xpi_bytes

        return Response(xpi_bytes(str(request.base_url)), media_type="application/x-xpinstall",
                        headers={"Content-Disposition": f'attachment; filename="zotllm-{__version__}.xpi"'})

    @app.get("/api/plugin/info")
    def plugin_info(request: Request, client: str = "", version: str = ""):
        if client == "zotero-plugin":
            engine.store.set_meta("plugin_seen", str(time.time()))
            engine.store.set_meta("plugin_version", version[:20] or "0")
        base = str(request.base_url)
        return {"version": __version__, "ui_url": base, "launcher": launcher_command()}

    @app.post("/api/plugin/index")
    def plugin_index(body: dict = Body(...)):
        """Rechtsklick in Zotero: Sammlung(en) bzw. Einträge indexieren.

        Sammlungen, die noch in keinem Wissenskorpus sind, erhalten einen eigenen Korpus (Name der Sammlung),
        damit sie künftig mit aktualisiert werden und bei Fragen auswählbar sind."""
        lib = body.get("lib") or "users/0"
        cols = [f"{lib}:{k}" for k in body.get("collections") or []]
        items = [f"{lib}:{k}" for k in body.get("items") or []]
        if cols:
            known = set(engine.corpus_sources())
            try:
                fetch_tree(engine)  # Sammlungsnamen aktualisieren
            except Exception:  # noqa: BLE001
                pass
            for src, info in zip(cols, describe_sources(engine, cols)):
                if src in known:
                    continue
                name, n = info["label"], 2
                taken = {c["name"].casefold() for c in engine.store.corpora()}
                while name.casefold() in taken:
                    name, n = f"{info['label']} ({n})", n + 1
                cid = engine.store.create_corpus(name, [src], "Aus Zotero per Rechtsklick angelegt")
                engine.store.assign_corpus(engine.active_project_id(), cid)
        return index_run({"sync": True, "collections": cols or None, "items": items or None})

    @app.get("/api/app/info")
    def app_info():
        from zotllm import paths

        return {"version": __version__, "data_dir": str(paths.data_dir()), "config_dir": str(paths.config_dir()),
                "log_dir": str(paths.log_dir()), "keystore": keys.backend_info(), "desktop": on_open_ui is not None,
                "frozen": bool(getattr(sys, "frozen", False))}

    @app.post("/api/ui/open")
    def ui_open(body: dict = Body(default={})):
        """Programmfenster zeigen (zweiter Programmstart, Zotero-Plugin). Ohne Fenster: shown=false."""
        params = {k: str(v) for k, v in (body or {}).items() if k in ("view", "tab", "collection", "items", "corpus")}
        if on_open_ui is None:
            return {"shown": False}
        return {"shown": bool(on_open_ui(params))}

    # -- Updates ------------------------------------------------------------------------------------
    @app.post("/api/update/check")
    def update_check(body: dict = Body(default={})):
        from zotllm import updates

        try:
            return updates.check(body.get("url") or engine.settings.update_url)
        except updates.UpdateError as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/update/install")
    def update_install(body: dict = Body(...)):
        from zotllm import updates

        if engine.jobs.running("index"):
            raise HTTPException(409, "Bitte zuerst die laufende Indexierung abbrechen oder abwarten.")
        try:
            path = updates.download_installer(body.get("installer") or "", body.get("sha256") or "")
        except updates.UpdateError as e:
            raise HTTPException(400, str(e)) from e
        except OSError as e:
            raise HTTPException(502, f"Download fehlgeschlagen: {e}") from e
        started = updates.run_installer(path)
        if started and on_exit:
            threading.Timer(1.0, on_exit).start()
        return {"started": started, "path": str(path)}

    @app.post("/api/shutdown")
    def shutdown():
        if on_exit:
            threading.Timer(0.5, on_exit).start()
        return {"ok": True}

    # -- Recherche ----------------------------------------------------------------------------------
    # Modul „Recherche“ (Paket zotllm.research): Schnittstelle /api/research/…; Host-Prüfung und X-ZotLLM gelten auch hier
    install_research(app, research)

    return app
