"""Embeddings über Cloud-APIs (OpenAI, Gemini, OpenAI-kompatible Server)."""

from __future__ import annotations

import numpy as np

from zotivity.embeddings.base import Embedder, EmbeddingError
from zotivity.keystore import get_store


class OpenAIEmbedder(Embedder):
    provider = "openai"
    max_batch = 256

    def __init__(self, cfg, provider: str = "openai"):
        super().__init__(cfg)
        import openai

        self.provider = provider
        key = get_store().get(provider)
        if provider == "openai" and not key:
            raise EmbeddingError("Kein OpenAI-API-Schlüssel gespeichert.")
        kwargs = {"api_key": key or "not-needed", "timeout": cfg.request_timeout, "max_retries": 4}
        if provider != "openai":
            if not cfg.base_url:
                raise EmbeddingError("Für einen OpenAI-kompatiblen Server muss die Basis-URL gesetzt sein.")
            kwargs["base_url"] = cfg.base_url
        self._openai = openai
        self._client = openai.OpenAI(**kwargs)

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.max_batch):
            batch = texts[i : i + self.max_batch]
            kwargs = {"model": self.model, "input": batch}
            if self.cfg.dimensions:
                kwargs["dimensions"] = self.cfg.dimensions
            try:
                resp = self._client.embeddings.create(**kwargs)
            except self._openai.AuthenticationError as e:
                raise EmbeddingError("API-Schlüssel ungültig.") from e
            except self._openai.NotFoundError as e:
                raise EmbeddingError(f"Embedding-Modell „{self.model}“ nicht gefunden.") from e
            except (self._openai.APIConnectionError, self._openai.RateLimitError,
                    self._openai.InternalServerError) as e:
                raise EmbeddingError(f"Embedding-Dienst vorübergehend nicht verfügbar: {e}", transient=True) from e
            except self._openai.APIError as e:
                raise EmbeddingError(f"Embedding-Fehler: {e}") from e
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return np.asarray(out, dtype=np.float32)

    def list_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self._client.models.list() if "embed" in m.id)
        except Exception:  # noqa: BLE001
            return []


class GeminiEmbedder(Embedder):
    provider = "gemini"
    max_batch = 100

    def __init__(self, cfg):
        super().__init__(cfg)
        from google import genai
        from google.genai import types

        key = get_store().get("gemini")
        if not key:
            raise EmbeddingError("Kein Gemini-API-Schlüssel gespeichert.")
        self._types = types
        self._client = genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=int(cfg.request_timeout * 1000))
        )
        self._use_task_type = True

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        types = self._types
        out: list[list[float]] = []
        for i in range(0, len(texts), self.max_batch):
            batch = texts[i : i + self.max_batch]
            cfg_kwargs = {}
            if self._use_task_type:
                cfg_kwargs["task_type"] = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
            if self.cfg.dimensions:
                cfg_kwargs["output_dimensionality"] = self.cfg.dimensions
            try:
                resp = self._client.models.embed_content(
                    model=self.model, contents=batch, config=types.EmbedContentConfig(**cfg_kwargs)
                )
            except Exception as e:  # noqa: BLE001
                if self._use_task_type and "task" in str(e).lower():
                    self._use_task_type = False
                    return self._embed(texts, is_query)
                text = str(e).lower()
                transient = any(s in text for s in ("429", "500", "502", "503", "504", "unavailable", "timeout",
                                                    "timed out", "connection", "resource_exhausted"))
                raise EmbeddingError(f"Gemini-Embedding-Fehler: {e}", transient=transient) from e
            out.extend(e.values for e in resp.embeddings)
        return np.asarray(out, dtype=np.float32)

    def list_models(self) -> list[str]:
        try:
            names = []
            for m in self._client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if "embedContent" in actions or "embed" in (m.name or ""):
                    names.append(m.name.removeprefix("models/"))
            return sorted(names)
        except Exception:  # noqa: BLE001
            return []
