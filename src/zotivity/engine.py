"""Zentrale Laufzeitobjekte: Einstellungen, Index, Zotero-Client, Embedder, Vektorindex."""

from __future__ import annotations

import logging
import threading

from zotivity import i18n, paths
from zotivity.embeddings import Embedder, EmbeddingError, make_embedder
from zotivity.index.store import SearchFilter, Store
from zotivity.index.vectors import VectorIndex
from zotivity.jobs import JobManager, JobQueue
from zotivity.settings import EmbeddingSettings, Settings, SettingsStore
from zotivity.zotero import ZoteroClient

log = logging.getLogger(__name__)

# Was ein Projekt vom Embedding-Modell festhält (Server-Adresse, Threads usw. bleiben global)
PROJECT_EMBEDDING_KEYS = ("provider", "model", "query_prefix", "document_prefix", "dimensions")


def project_embedding(raw: dict | None) -> dict | None:
    """Geprüfte Projekt-Einstellung des Embedding-Modells; None = kein eigenes Modell."""
    if not raw or not raw.get("provider") or not raw.get("model"):
        return None
    cfg = EmbeddingSettings.model_validate({k: raw.get(k) for k in PROJECT_EMBEDDING_KEYS if k in raw})
    return {k: getattr(cfg, k) for k in PROJECT_EMBEDDING_KEYS}


class Engine:
    def __init__(self, settings_store: SettingsStore | None = None, store: Store | None = None):
        self.settings_store = settings_store or SettingsStore()
        self.store = store or Store(paths.index_db_file())
        self.jobs = JobManager()
        self.index_lock = threading.Lock()  # höchstens ein Indexierlauf gleichzeitig
        # Weitere von Hand gestartete Läufe warten hier, bis der laufende fertig ist
        self.index_queue = JobQueue(self.jobs, "index", "index")
        self._lock = threading.RLock()
        self._zotero: ZoteroClient | None = None
        self._zotero_url: str | None = None
        self._embedder: Embedder | None = None
        self._embedder_cfg: str | None = None
        self._vindex: VectorIndex | None = None
        self._space: str | None = None
        self.settings_store.on_change(self._on_settings_change)
        i18n.set_language(self.settings_store.get().language)
        self.ensure_project()

    # -- Projekte -------------------------------------------------------------------------
    def ensure_project(self) -> int:
        """Es gibt immer mindestens ein Projekt; Bestehendes ohne Projekt landet in „Allgemein“."""
        projects = self.store.projects()
        if projects:
            return projects[0]["id"]
        pid = self.store.create_project("Allgemein", "Alles, was keinem eigenen Projekt zugeordnet ist.")
        self.store.adopt_orphans(pid)
        return pid

    def active_project_id(self) -> int:
        """Zuletzt geöffnetes Projekt (z. B. für Korpora, die das Zotero-Plugin anlegt)."""
        self.ensure_project()
        projects = self.store.projects()
        candidates = [p for p in projects if not p.get("archived_at")] or projects
        return max(candidates, key=lambda p: p.get("opened_at") or 0)["id"]

    def apply_project_embedding(self, project_id: int) -> dict | None:
        """Hat das Projekt ein eigenes Embedding-Modell, dieses aktivieren. Liefert die Umstellung oder None."""
        p = self.store.project(project_id)
        pin = (p or {}).get("embedding")
        if not pin:
            return None
        cur = self.settings.embedding
        if all(getattr(cur, k) == pin.get(k) for k in PROJECT_EMBEDDING_KEYS):
            return None
        self.settings_store.update({"embedding": {k: pin.get(k) for k in PROJECT_EMBEDDING_KEYS}})
        log.info("Embedding-Modell des Projekts %s aktiviert: %s/%s", project_id, pin["provider"], pin["model"])
        return {"provider": pin["provider"], "model": pin["model"]}

    def shutdown(self) -> None:
        """Hilfsprozesse beenden (eingebaute Embedding-Laufzeit)."""
        from zotivity.embeddings.llama_runtime import get_runtime

        get_runtime().stop_all()

    # -- Wissenskorpora -------------------------------------------------------------------
    def corpus_sources(self, corpus_id: int | None = None) -> list[str]:
        """Quellen eines Korpus bzw. (ohne ID) aller Korpora zusammen."""
        if corpus_id is not None:
            c = self.store.corpus(int(corpus_id))
            return c["sources"] if c else []
        return sorted({s for c in self.store.corpora() for s in c["sources"]})

    @staticmethod
    def libraries_of(sources: list[str]) -> list[str]:
        return sorted({s.split(":", 1)[0] for s in sources if ":" in s})

    def make_filter(self, filters: dict | None) -> SearchFilter:
        """Filter aus der Oberfläche. Korpora werden in ihre Quellen aufgelöst:
        'corpus_id' (einer), 'corpus_ids' (mehrere, Vereinigung) oder 'project_id' (alle Korpora des Projekts)."""
        filters = dict(filters or {})
        ids: list[int] | None = None
        corpus_id = filters.pop("corpus_id", None)
        corpus_ids = filters.pop("corpus_ids", None)
        project_id = filters.pop("project_id", None)
        if corpus_id not in (None, "", "all"):
            ids = [int(corpus_id)]
        elif corpus_ids:
            ids = [int(c) for c in corpus_ids]
        elif project_id not in (None, ""):
            ids = self.store.project_corpus_ids(int(project_id))
        f = SearchFilter.from_dict(filters)
        if ids is not None:
            sources = sorted({s for cid in ids for s in self.corpus_sources(cid)})
            # Leere Auswahl: bewusst nichts finden statt alles
            f.collections = list(f.collections) + (sources or ["__leer__:__leer__"])
        return f

    # -- Dubletten (index/duplicates.py) ----------------------------------------------
    def copy_resolution(self) -> dict[tuple[str, str], tuple[str, str]]:
        """Nicht gewählte Kopie eines Werks → gewählte Kopie (leer, wenn es keine Dubletten gibt)."""
        from zotivity.index import duplicates

        return duplicates.hidden_copies(self.store, self.settings.indexing.duplicate_library)

    def resolve_copies(self, scope: set[tuple[str, str]]) -> set[tuple[str, str]]:
        """Umfang auf die gewählten Kopien abbilden: Ein Werk gehört dazu, wenn irgendeine seiner Kopien dazugehört."""
        hidden = self.copy_resolution()
        return {hidden.get(k, k) for k in scope} if hidden else scope

    @property
    def settings(self) -> Settings:
        return self.settings_store.get()

    def _on_settings_change(self, old: Settings, new: Settings) -> None:
        if old.language != new.language:
            i18n.set_language(new.language)
        if old.embedding != new.embedding:
            with self._lock:
                self._embedder = None
                self._vindex = None
                self._space = None
        if old.zotero.api_url != new.zotero.api_url:
            with self._lock:
                self._zotero = None

    # -- Zotero ---------------------------------------------------------------------
    def zotero(self) -> ZoteroClient:
        url = self.settings.zotero.api_url
        with self._lock:
            if self._zotero is None or self._zotero_url != url:
                self._zotero = ZoteroClient(url)
                self._zotero_url = url
            return self._zotero

    # -- Embeddings ------------------------------------------------------------------
    def embedder(self) -> Embedder:
        cfg = self.settings.embedding
        key = cfg.model_dump_json()
        with self._lock:
            if self._embedder is None or self._embedder_cfg != key:
                emb = make_embedder(cfg)
                self._resolve_dim(emb)
                self._embedder = emb
                self._embedder_cfg = key
                self._vindex = None
            return self._embedder

    def _resolve_dim(self, emb: Embedder) -> None:
        """Dimension aus einem bereits bekannten Raum übernehmen – spart einen Modellaufruf."""
        if emb._dim is not None:
            return
        for s in self.store.spaces():
            if s["provider"] == emb.provider and s["model"] == emb.model:
                import json

                params = json.loads(s["params"] or "{}")
                if params == emb.space_params:
                    emb._dim = int(s["dim"])
                    return

    def space(self) -> str:
        emb = self.embedder()
        space = emb.space_id
        self.store.ensure_space(space, emb.provider, emb.model, emb.dim, emb.space_params)
        return space

    def vector_index(self) -> tuple[str, VectorIndex]:
        with self._lock:
            emb = self.embedder()
            space = self.space()
            if self._vindex is None or self._space != space:
                ids, mat = self.store.load_vectors(space, emb.dim)
                vi = VectorIndex(emb.dim)
                vi.load(ids, mat)
                self._vindex, self._space = vi, space
                log.info("Vektorindex geladen: %s (%d Vektoren)", space, len(ids))
            return self._space, self._vindex

    def vector_index_if_loaded(self) -> VectorIndex | None:
        return self._vindex

    def reset_embedder(self) -> None:
        """Nach Schlüsseländerungen: Embedder neu erzeugen (liest den Schlüssel beim Erstellen)."""
        with self._lock:
            self._embedder = None
            self._embedder_cfg = None

    def reset_vector_index(self) -> None:
        """Beim nächsten Zugriff neu aus der Datenbank laden (z. B. nach Löschungen)."""
        with self._lock:
            self._vindex = None

    def embedding_label(self, cfg=None) -> str:
        """Anzeigename des Embedding-Modells (eingebaute Modelle: Name aus dem Katalog)."""
        cfg = cfg or self.settings.embedding
        if cfg.provider == "builtin":
            from zotivity.embeddings import model_catalog

            entry = model_catalog.get(cfg.model)
            if entry is not None:
                return entry.name
        return cfg.model

    def embedding_status(self) -> dict:
        cfg = self.settings.embedding
        try:
            emb = self.embedder()
            space = emb.space_id
            return {"ok": True, "provider": cfg.provider, "model": cfg.model, "label": self.embedding_label(cfg),
                    "dim": emb.dim, "space": space}
        except EmbeddingError as e:
            return {"ok": False, "provider": cfg.provider, "model": cfg.model, "label": self.embedding_label(cfg),
                    "error": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "provider": cfg.provider, "model": cfg.model, "label": self.embedding_label(cfg),
                    "error": str(e)}
