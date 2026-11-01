"""Presets für die Such- und Antwortwerte.

Ein Preset enthält nur Werte, die ohne Neuindexierung wirken (Suche, Denktiefe, Kontext) – keine Zerlegung,
kein Embedding, keine Anbieter oder Schlüssel. Eingebaute Presets sind fest; eigene liegen in den Einstellungen.
"""

from __future__ import annotations

from typing import Any

from zotivity.settings import RetrievalSettings, Settings

# Felder, die ein Preset setzen darf (Bereich.Feld)
FIELDS = (
    "retrieval.top_k", "retrieval.max_chunks_per_doc", "retrieval.candidate_k", "retrieval.hybrid_weight",
    "retrieval.rrf_k", "retrieval.mmr_lambda", "retrieval.min_similarity", "retrieval.neighbor_chunks",
    "retrieval.multi_query", "retrieval.n_queries", "retrieval.research_rounds", "retrieval.rerank",
    "retrieval.rerank_candidates", "retrieval.context_token_budget", "llm.effort",
)

_DEFAULT = RetrievalSettings()

BUILTIN: dict[str, dict[str, Any]] = {
    "schnell": {
        "label": "Schnell", "description": "Rasche Übersicht mit wenigen Textstellen – günstig, wenige Sekunden.",
        "values": {"retrieval.top_k": 8, "retrieval.max_chunks_per_doc": 2, "retrieval.candidate_k": 40,
                   "retrieval.hybrid_weight": 0.6, "retrieval.rrf_k": 60, "retrieval.mmr_lambda": 0.7,
                   "retrieval.min_similarity": 0.0, "retrieval.neighbor_chunks": 0, "retrieval.multi_query": False,
                   "retrieval.n_queries": 4, "retrieval.research_rounds": 0, "retrieval.rerank": "none",
                   "retrieval.rerank_candidates": 40, "retrieval.context_token_budget": 8000, "llm.effort": "low"},
    },
    "ausgewogen": {
        "label": "Ausgewogen", "description": "Standard: Mehrfachsuche auf Deutsch und Englisch, 15 Textstellen.",
        "values": {f"retrieval.{k}": getattr(_DEFAULT, k) for k in (
            "top_k", "max_chunks_per_doc", "candidate_k", "hybrid_weight", "rrf_k", "mmr_lambda", "min_similarity",
            "neighbor_chunks", "multi_query", "n_queries", "research_rounds", "rerank", "rerank_candidates",
            "context_token_budget")} | {"llm.effort": ""},
    },
    "gruendlich": {
        "label": "Gründlich", "description": "Vollständigkeit vor Tempo: mehr Suchanfragen, Nachrecherche, "
                                           "Neusortierung, mehr Kontext – etwa 1–2 Minuten, 3–5-mal mehr Tokens.",
        "values": {"retrieval.top_k": 30, "retrieval.max_chunks_per_doc": 4, "retrieval.candidate_k": 200,
                   "retrieval.hybrid_weight": 0.6, "retrieval.rrf_k": 60, "retrieval.mmr_lambda": 0.65,
                   "retrieval.min_similarity": 0.0, "retrieval.neighbor_chunks": 1, "retrieval.multi_query": True,
                   "retrieval.n_queries": 8, "retrieval.research_rounds": 2, "retrieval.rerank": "llm",
                   "retrieval.rerank_candidates": 60, "retrieval.context_token_budget": 40000, "llm.effort": "high"},
    },
    "wortgenau": {
        "label": "Wortgenau", "description": "Für Zitate, Fachbegriffe und Namen: mehr Gewicht auf die "
                                           "Stichwortsuche, Nachbarabschnitte für den Zusammenhang.",
        "values": {"retrieval.top_k": 12, "retrieval.max_chunks_per_doc": 3, "retrieval.candidate_k": 100,
                   "retrieval.hybrid_weight": 0.3, "retrieval.rrf_k": 60, "retrieval.mmr_lambda": 0.9,
                   "retrieval.min_similarity": 0.0, "retrieval.neighbor_chunks": 1, "retrieval.multi_query": False,
                   "retrieval.n_queries": 4, "retrieval.research_rounds": 0, "retrieval.rerank": "none",
                   "retrieval.rerank_candidates": 40, "retrieval.context_token_budget": 16000, "llm.effort": ""},
    },
}


def _get(settings: Settings, path: str):
    section, key = path.split(".")
    return getattr(getattr(settings, section), key)


def current_values(settings: Settings) -> dict[str, Any]:
    return {f: _get(settings, f) for f in FIELDS}


def all_presets(settings: Settings) -> dict[str, dict]:
    out = {k: {**v, "builtin": True} for k, v in BUILTIN.items()}
    for key, p in (settings.presets or {}).items():
        out[key] = {"label": p.get("label") or key, "description": p.get("description", ""),
                    "values": {f: v for f, v in (p.get("values") or {}).items() if f in FIELDS}, "builtin": False}
    return out


def patch_for(values: dict[str, Any]) -> dict:
    """Preset-Werte → Teil-Aktualisierung der Einstellungen."""
    patch: dict[str, dict] = {}
    for path, value in values.items():
        if path in FIELDS:
            section, key = path.split(".")
            patch.setdefault(section, {})[key] = value
    return patch


def differences(settings: Settings, values: dict[str, Any]) -> list[dict]:
    cur = current_values(settings)
    return [{"field": f, "preset": v, "current": cur[f]} for f, v in values.items() if f in cur and cur[f] != v]


def slug(label: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "preset"
