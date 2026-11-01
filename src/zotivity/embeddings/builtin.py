"""Eingebaute Embeddings: Modelle aus dem Modellkatalog, ausgeführt mit llama.cpp (siehe llama_runtime)."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from zotivity.embeddings import model_catalog, model_store
from zotivity.embeddings.base import Embedder, EmbeddingError
from zotivity.embeddings.llama_runtime import ServerSpec, get_runtime
from zotivity.index.vectors import normalize


class BuiltinEmbedder(Embedder):
    provider = "builtin"

    def __init__(self, cfg):
        super().__init__(cfg)
        entry = model_catalog.get(cfg.model)
        if entry is None:
            raise EmbeddingError(f"Das Modell „{cfg.model}“ steht nicht im Modellkatalog.")
        rec = model_store.record(entry.id)
        if rec is None:
            raise EmbeddingError(f"„{entry.name}“ ist noch nicht heruntergeladen – unter Einstellungen → Embedding "
                                 "herunterladen.")
        self.entry, self.record = entry, rec
        rt = entry.runtime
        self.query_prefix = cfg.query_prefix if cfg.query_prefix is not None else rt.query_prefix
        self.document_prefix = cfg.document_prefix if cfg.document_prefix is not None else rt.document_prefix
        gg = rec.get("gguf") or {}
        self.pooling = rt.pooling or gg.get("pooling") or ""
        self.ctx = min(rt.ctx, int(gg["context"])) if gg.get("context") else rt.ctx
        # Grobe Obergrenze vorab; die Laufzeit kürzt zu lange Abschnitte genau auf die Tokenzahl
        self.max_input_chars = self.ctx * 6
        full = gg.get("dim") or entry.dim
        self.full_dim = int(full) if full else None
        dims = cfg.dimensions
        self._dim = dims if dims and self.full_dim and dims < self.full_dim else self.full_dim
        self.last_tokens = 0

    @property
    def model_path(self) -> str:
        return self.record["abs_path"]

    @property
    def space_params(self) -> dict:
        # Datei und Pooling gehören zum Vektorraum: eine andere Datei kann andere Vektoren liefern
        return {"query_prefix": self.query_prefix, "document_prefix": self.document_prefix,
                "file": self.record.get("sha256", "")[:12], "pooling": self.pooling}

    @property
    def space_id(self) -> str:
        p = self.space_params
        params = {"q": p["query_prefix"], "d": p["document_prefix"], "f": p["file"], "p": p["pooling"]}
        h = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:6]
        return f"{self.provider}:{self.model}:{self.dim}:{h}"

    def spec(self) -> ServerSpec:
        return ServerSpec(model_path=self.model_path, pooling=self.pooling, ctx=self.ctx,
                          parallel=self.cfg.parallel, threads=self.cfg.num_thread)

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        runtime = get_runtime()
        runtime.keep_alive = self.cfg.keep_alive_minutes * 60
        vecs, self.last_tokens = runtime.embed(self.spec(), texts)
        if self._dim and vecs.shape[1] > self._dim:  # Matryoshka: vorne abschneiden, neu normieren
            vecs = normalize(vecs[:, : self._dim])
        return vecs

    def list_models(self) -> list[str]:
        return sorted(model_store.installed())
