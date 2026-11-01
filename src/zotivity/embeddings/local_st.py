"""Lokale Embeddings über sentence-transformers (optional: pip install "zotivity[local]").

Nützlich für Modelle, die (noch) nicht in Ollama verfügbar sind, z. B.
google/embeddinggemma-2. Gemma-Modelle erfordern eine Lizenzbestätigung auf
Hugging Face und ggf. `hf auth login`.
"""

from __future__ import annotations

import threading

import numpy as np

from zotivity.embeddings.base import Embedder, EmbeddingError

_models: dict[str, object] = {}
_lock = threading.Lock()


class SentenceTransformerEmbedder(Embedder):
    provider = "sentence_transformers"

    def __init__(self, cfg):
        super().__init__(cfg)
        # Eigene Präfixe nur, wenn ausdrücklich gesetzt – sonst nutzt das Modell seine Prompts
        self.query_prefix = cfg.query_prefix or ""
        self.document_prefix = cfg.document_prefix or ""
        self.max_input_chars = 32000

    def _model(self):
        with _lock:
            if self.model not in _models:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as e:
                    raise EmbeddingError(
                        "sentence-transformers ist nicht installiert: pip install \"zotivity[local]\""
                    ) from e
                kwargs = {}
                if self.cfg.dimensions:
                    kwargs["truncate_dim"] = self.cfg.dimensions
                _models[self.model] = SentenceTransformer(self.model, **kwargs)
            return _models[self.model]

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        model = self._model()
        fn = getattr(model, "encode_query" if is_query else "encode_document", None)
        if fn is None:
            fn = model.encode
        vecs = fn(texts, batch_size=self.cfg.batch_size, convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)
