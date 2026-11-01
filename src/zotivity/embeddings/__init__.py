"""Austauschbare Embedding-Anbieter."""

from __future__ import annotations

from zotivity.embeddings.base import Embedder, EmbeddingError
from zotivity.settings import EmbeddingSettings


def make_embedder(cfg: EmbeddingSettings) -> Embedder:
    p = cfg.provider
    if p == "builtin":
        from zotivity.embeddings.builtin import BuiltinEmbedder

        return BuiltinEmbedder(cfg)
    if p == "ollama":
        from zotivity.embeddings.ollama import OllamaEmbedder

        return OllamaEmbedder(cfg)
    if p in ("openai", "openai_compatible"):
        from zotivity.embeddings.cloud import OpenAIEmbedder

        return OpenAIEmbedder(cfg, provider=p)
    if p == "gemini":
        from zotivity.embeddings.cloud import GeminiEmbedder

        return GeminiEmbedder(cfg)
    if p == "sentence_transformers":
        from zotivity.embeddings.local_st import SentenceTransformerEmbedder

        return SentenceTransformerEmbedder(cfg)
    raise EmbeddingError(f"Unbekannter Embedding-Anbieter: {p}")


__all__ = ["Embedder", "EmbeddingError", "make_embedder"]
