from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod

import numpy as np

from zotivity.catalog import embedding_preset
from zotivity.settings import EmbeddingSettings


class EmbeddingError(RuntimeError):
    """transient=True: vorübergehend (Dienst nicht erreichbar, überlastet) – später erneut versuchen lohnt sich."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class Embedder(ABC):
    provider: str = ""

    def __init__(self, cfg: EmbeddingSettings):
        self.cfg = cfg
        self.model = cfg.model
        preset = embedding_preset(cfg.model)
        self.query_prefix = cfg.query_prefix if cfg.query_prefix is not None else preset.query_prefix
        self.document_prefix = cfg.document_prefix if cfg.document_prefix is not None else preset.document_prefix
        self.max_input_chars = preset.max_input_chars
        self._dim: int | None = cfg.dimensions

    # -- von Unterklassen zu implementieren ----------------------------------------
    @abstractmethod
    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        """Rohe Vektoren (n × dim)."""

    def list_models(self) -> list[str]:
        return []

    # -- gemeinsame Logik ----------------------------------------------------------------
    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = int(self._embed(["dimension probe"], is_query=True).shape[1])
        return self._dim

    @property
    def space_id(self) -> str:
        """Eindeutige Kennung des Vektorraums. Präfixe gehören dazu, weil sie die Vektoren verändern."""
        params = {"q": self.query_prefix, "d": self.document_prefix}
        h = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:6]
        return f"{self.provider}:{self.model}:{self.dim}:{h}"

    @property
    def space_params(self) -> dict:
        return {"query_prefix": self.query_prefix, "document_prefix": self.document_prefix}

    def _prep(self, texts: list[str], prefix: str) -> list[str]:
        out = []
        for t in texts:
            t = (prefix + t) if prefix else t
            out.append(t[: self.max_input_chars])
        return out

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        vecs = self._embed(self._prep(texts, self.document_prefix), is_query=False)
        self._check(vecs, len(texts))
        return vecs

    def embed_query(self, text: str) -> np.ndarray:
        vecs = self._embed(self._prep([text], self.query_prefix), is_query=True)
        self._check(vecs, 1)
        return vecs[0]

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        vecs = self._embed(self._prep(texts, self.query_prefix), is_query=True)
        self._check(vecs, len(texts))
        return vecs

    def _check(self, vecs: np.ndarray, n: int) -> None:
        if vecs.ndim != 2 or vecs.shape[0] != n:
            raise EmbeddingError(f"Unerwartete Antwort des Embedding-Modells: {vecs.shape}, erwartet {n} Vektoren")
        if self._dim is None:
            self._dim = int(vecs.shape[1])
        elif vecs.shape[1] != self._dim:
            raise EmbeddingError(f"Dimension {vecs.shape[1]} statt {self._dim}")

    def test(self) -> dict:
        v = self.embed_query("Test der Verbindung")
        return {"ok": True, "dim": int(v.shape[0]), "space": self.space_id}
