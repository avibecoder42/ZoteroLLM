"""Optionale Neusortierung der Treffer (Reranking)."""

from __future__ import annotations

import logging
import threading

from zotivity.llm import ChatModel, GenParams
from zotivity.retrieval.search import Hit

log = logging.getLogger(__name__)


class LLMReranker:
    """Das Hilfsmodell bewertet jede Textstelle von 0–10. Kostet einen zusätzlichen Aufruf."""

    def __init__(self, model: ChatModel, effort: str = "low"):
        self.model = model
        self.effort = effort

    def rerank(self, query: str, hits: list[Hit]) -> None:
        if not hits:
            return
        passages = "\n\n".join(
            f"[{i}] {h.item.get('creator_summary', '')} {h.item.get('year') or ''}: {h.chunk['text'][:1200]}"
            for i, h in enumerate(hits)
        )
        prompt = (
            f"Frage: {query}\n\nTextstellen:\n{passages}\n\n"
            "Bewerte für jede Textstelle, wie gut sie zur Beantwortung der Frage beiträgt "
            "(0 = irrelevant, 10 = zentral). Antworte als JSON: {\"scores\": [{\"id\": 0, \"score\": 7}, ...]}"
        )
        try:
            data = self.model.complete_json(
                "Du bewertest die Relevanz wissenschaftlicher Textstellen. Antworte nur mit JSON.",
                prompt, GenParams(max_tokens=4000, effort=self.effort),
            )
            for entry in (data or {}).get("scores", []):
                i = int(entry.get("id", -1))
                if 0 <= i < len(hits):
                    note = max(0.0, min(10.0, float(entry.get("score", 0))))
                    hits[i].rerank_score = note + hits[i].score  # Gleichstände auflösen
                    hits[i].rerank_relevance = note / 10
        except Exception as e:  # noqa: BLE001
            log.warning("LLM-Reranking fehlgeschlagen: %s", e)


_ce_models: dict[str, object] = {}
_ce_lock = threading.Lock()


class CrossEncoderReranker:
    """Lokales Cross-Encoder-Modell (z. B. BAAI/bge-reranker-v2-m3), benötigt sentence-transformers."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    def _model(self):
        with _ce_lock:
            if self.model_name not in _ce_models:
                try:
                    from sentence_transformers import CrossEncoder
                except ImportError as e:
                    raise RuntimeError(
                        "Für den Cross-Encoder wird sentence-transformers benötigt: pip install \"zotivity[local]\""
                    ) from e
                _ce_models[self.model_name] = CrossEncoder(self.model_name)
            return _ce_models[self.model_name]

    def rerank(self, query: str, hits: list[Hit]) -> None:
        if not hits:
            return
        scores = self._model().predict([(query, h.chunk["text"]) for h in hits])
        for h, s in zip(hits, scores):
            h.rerank_score = float(s)
            # bge-reranker & Co. liefern mit Sigmoid-Aktivierung Werte zwischen 0 und 1
            h.rerank_relevance = float(s) if 0.0 <= float(s) <= 1.0 else None
