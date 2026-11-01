from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import numpy as np

from zotivity.embeddings.base import Embedder, EmbeddingError


def ollama_base_url(url: str | None) -> str:
    return (url or "http://127.0.0.1:11434").rstrip("/")


class OllamaEmbedder(Embedder):
    provider = "ollama"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base_url = ollama_base_url(cfg.base_url)
        self._http = httpx.Client(timeout=httpx.Timeout(cfg.request_timeout, connect=5.0), trust_env=False)

    def _embed(self, texts: list[str], is_query: bool) -> np.ndarray:
        payload = {"model": self.model, "input": texts, "truncate": True, "keep_alive": "10m"}
        if self.cfg.dimensions:
            payload["dimensions"] = self.cfg.dimensions
        options = {}
        if self.cfg.num_thread:
            options["num_thread"] = self.cfg.num_thread
        if self.cfg.device == "cpu":
            options["num_gpu"] = 0
        elif self.cfg.device == "gpu":
            options["num_gpu"] = 999
        if options:
            payload["options"] = options
        try:
            r = self._http.post(f"{self.base_url}/api/embed", json=payload)
        except httpx.TransportError as e:
            raise EmbeddingError("Ollama ist nicht erreichbar. Läuft Ollama?", transient=True) from e
        if r.status_code == 404:
            raise EmbeddingError(
                f"Modell „{self.model}“ ist in Ollama nicht vorhanden. "
                f"In den Einstellungen herunterladen oder: ollama pull {self.model}"
            )
        if r.status_code >= 400:
            raise EmbeddingError(f"Ollama-Fehler {r.status_code}: {r.text[:300]}", transient=r.status_code >= 500)
        data = r.json()
        return np.asarray(data["embeddings"], dtype=np.float32)

    def list_models(self) -> list[str]:
        """Nur Embedding-Modelle: Ollama meldet je Modell seine Fähigkeiten (Sprachmodelle können nicht einbetten)."""
        try:
            r = self._http.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
        except httpx.HTTPError:
            return []
        out = []
        for m in r.json().get("models", []):
            name = m["name"]
            try:
                caps = self._http.post(f"{self.base_url}/api/show", json={"model": name}, timeout=10).json().get(
                    "capabilities")
            except (httpx.HTTPError, ValueError):
                continue  # beschädigtes oder nicht lesbares Modell
            if caps is None:  # ältere Ollama-Version ohne Angabe: nach dem Namen
                if "embed" in name or name.split(":")[0] in ("bge-m3", "mxbai-embed-large", "all-minilm"):
                    out.append(name)
            elif "embedding" in caps:
                out.append(name)
        return sorted(out)


def ollama_pull(base_url: str | None, model: str) -> Iterator[dict]:
    """Lädt ein Modell herunter; liefert Fortschrittsmeldungen von Ollama."""
    url = f"{ollama_base_url(base_url)}/api/pull"
    with httpx.Client(timeout=httpx.Timeout(None, connect=5.0), trust_env=False) as http:
        with http.stream("POST", url, json={"model": model, "stream": True}) as r:
            if r.status_code >= 400:
                raise EmbeddingError(f"Ollama-Fehler {r.status_code}: {r.read()[:300]!r}")
            for line in r.iter_lines():
                if line.strip():
                    msg = json.loads(line)
                    if "error" in msg:
                        raise EmbeddingError(msg["error"])
                    yield msg


def ollama_available(base_url: str | None) -> bool:
    try:
        r = httpx.get(f"{ollama_base_url(base_url)}/api/version", timeout=2.0, trust_env=False)
        return r.status_code == 200
    except httpx.HTTPError:
        return False
