"""Hybride Suche: Bedeutungssuche + Stichwortsuche, Fusion, Vielfalt (MMR)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np

from zotivity.engine import Engine
from zotivity.index.store import SearchFilter
from zotivity.settings import RetrievalSettings

log = logging.getLogger(__name__)

_STOP = set("""
der die das den dem des ein eine einer eines einem einen und oder aber auch als am an auf aus bei bis da dass
durch für gegen hat haben ist im in mit nach nicht noch nur ob ohne sich sie sind so über um unter von vor
war waren was welche welcher welches wie wird werden wo zu zum zur zwischen es er wir ihr ich du man kann
können sein seine ihre ihrem ihren dieser diese dieses diesem diesen jene mehr sehr gibt gab welche wurde wurden
the a an and or but of to in on at for with by from as is are was were be been being this that these those it
its their there which who whom what when where why how not no do does did can could would should may might
than then so such into over under about between through during within without also more most
""".split())

_WORD = re.compile(r"[\wäöüÄÖÜß]+(?:-[\wäöüÄÖÜß]+)*", re.UNICODE)
_SUFFIXES = ("ungen", "ung", "heit", "keit", "lich", "ische", "isch", "innen", "ern", "en", "er", "es", "e",
             "ies", "ing", "ers", "ed", "s")


def _stem(word: str) -> str:
    for suf in _SUFFIXES:
        if len(word) - len(suf) >= 5 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def fts_query(text: str, max_terms: int = 24) -> str:
    """Freitext → FTS5-Abfrage (ODER-Verknüpfung, Präfixsuche für Wortstämme)."""
    terms: list[str] = []
    seen: set[str] = set()
    for m in _WORD.finditer(text.lower()):
        w = m.group(0)
        if len(w) < 2 or w in _STOP or w.isdigit() and len(w) < 4:
            continue
        for part in w.split("-") if "-" in w else [w]:
            if len(part) < 2 or part in _STOP:
                continue
            stem = _stem(part)
            token = f'"{stem}"*' if len(stem) >= 4 else f'"{part}"'
            if token not in seen:
                seen.add(token)
                terms.append(token)
    return " OR ".join(terms[:max_terms])


@dataclass
class Hit:
    chunk_id: int
    score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    chunk: dict = field(default_factory=dict)
    item: dict = field(default_factory=dict)
    rerank_score: float | None = None
    # Relevanz laut Neusortierung auf 0–1 (Cross-Encoder: Wahrscheinlichkeit, Hilfsmodell: Note/10)
    rerank_relevance: float | None = None

    @property
    def doc_key(self) -> tuple[str, str]:
        return self.chunk["lib"], self.chunk["item_key"]


class Searcher:
    def __init__(self, engine: Engine):
        self.engine = engine

    @property
    def store(self):
        return self.engine.store

    def _allowed_ids(self, f: SearchFilter) -> np.ndarray | None:
        """Erlaubte Abschnitte. Dubletten: nur die gewählte Kopie eines Werks – sie zählt auch dort, wo nur eine
        andere Kopie im Filter liegt (z. B. ein Korpus aus einer Gruppe, gewählt ist die Kopie in Meine Bibliothek)."""
        allowed = self.store.allowed_items(f)
        hidden = self.engine.copy_resolution()
        if allowed is None:
            return self.store.chunk_ids_excluding(set(hidden)) if hidden else None
        if hidden:
            allowed = {hidden.get(k, k) for k in allowed}
        return self.store.chunk_ids_for_items(allowed)

    def candidates(
        self, queries: list[str], f: SearchFilter, cfg: RetrievalSettings, candidate_k: int | None = None,
        per_query: list[set[int]] | None = None,
    ) -> dict[int, Hit]:
        """Kandidaten aus allen Suchanfragen mit gewichteter Reciprocal Rank Fusion.
        per_query (optional) erhält je Suchanfrage die Menge der gefundenen Abschnitte."""
        candidate_k = candidate_k or cfg.candidate_k
        if per_query is not None:
            per_query[:] = [set() for _ in queries]
        allowed_ids = self._allowed_ids(f)
        if allowed_ids is not None and len(allowed_ids) == 0:
            return {}
        w_vec, w_kw = cfg.hybrid_weight, 1.0 - cfg.hybrid_weight
        hits: dict[int, Hit] = {}

        vec_results: list[list[tuple[int, float]]] = []
        if w_vec > 0:
            try:
                emb = self.engine.embedder()
                _, vindex = self.engine.vector_index()
                qvecs = emb.embed_queries(queries)
                for qv in qvecs:
                    vec_results.append(vindex.search(qv, candidate_k, allowed_ids))
            except Exception as e:  # noqa: BLE001
                log.warning("Bedeutungssuche nicht verfügbar: %s", e)
                if w_kw == 0:
                    raise
                vec_results = []

        for qi, res in enumerate(vec_results):
            for rank, (cid, sim) in enumerate(res):
                if sim < cfg.min_similarity:
                    continue
                h = hits.setdefault(cid, Hit(cid, 0.0))
                h.score += w_vec / (cfg.rrf_k + rank + 1)
                h.vector_score = max(h.vector_score or -1.0, sim)
                if per_query is not None:
                    per_query[qi].add(cid)

        if w_kw > 0:
            for qi, q in enumerate(queries):
                for rank, (cid, bm) in enumerate(self.store.fts_search(fts_query(q), candidate_k, allowed_ids)):
                    h = hits.setdefault(cid, Hit(cid, 0.0))
                    h.score += w_kw / (cfg.rrf_k + rank + 1)
                    h.keyword_score = max(h.keyword_score or 0.0, bm)
                    if per_query is not None:
                        per_query[qi].add(cid)
        return hits

    def hydrate(self, hits: list[Hit]) -> list[Hit]:
        rows = self.store.chunk_rows([h.chunk_id for h in hits])
        items = self.store.items({(r["lib"], r["item_key"]) for r in rows.values()})
        out = []
        for h in hits:
            row = rows.get(h.chunk_id)
            if not row:
                continue
            h.chunk = row
            h.item = items.get((row["lib"], row["item_key"]), {})
            out.append(h)
        return out

    def select(self, hits: list[Hit], k: int, cfg: RetrievalSettings) -> list[Hit]:
        """MMR-Auswahl mit Obergrenze pro Dokument."""
        if not hits:
            return []
        hits = sorted(hits, key=lambda h: -(h.rerank_score if h.rerank_score is not None else h.score))
        rel_raw = np.array([h.rerank_score if h.rerank_score is not None else h.score for h in hits], dtype=np.float32)
        rel = (rel_raw - rel_raw.min()) / (rel_raw.max() - rel_raw.min() + 1e-9)
        vecs = {}
        vi = self.engine.vector_index_if_loaded()
        if vi is not None and cfg.mmr_lambda < 1.0:
            vecs = vi.vectors_for([h.chunk_id for h in hits])
        selected: list[int] = []
        per_doc: dict[tuple[str, str], int] = {}
        remaining = list(range(len(hits)))
        lam = cfg.mmr_lambda
        while remaining and len(selected) < k:
            best, best_val = None, -1e9
            for i in remaining:
                if per_doc.get(hits[i].doc_key, 0) >= cfg.max_chunks_per_doc:
                    continue
                penalty = 0.0
                vi_ = vecs.get(hits[i].chunk_id)
                if vi_ is not None and selected and lam < 1.0:
                    sims = [float(vi_ @ vecs[hits[j].chunk_id]) for j in selected if hits[j].chunk_id in vecs]
                    penalty = max(sims) if sims else 0.0
                val = lam * rel[i] - (1 - lam) * penalty
                if val > best_val:
                    best, best_val = i, val
            if best is None:
                break
            selected.append(best)
            remaining.remove(best)
            per_doc[hits[best].doc_key] = per_doc.get(hits[best].doc_key, 0) + 1
        return [hits[i] for i in selected]

    def search(
        self,
        queries: list[str] | str,
        f: SearchFilter | None = None,
        cfg: RetrievalSettings | None = None,
        k: int | None = None,
        reranker=None,
        rerank_query: str | None = None,
    ) -> list[Hit]:
        cfg = cfg or self.engine.settings.retrieval
        f = f or SearchFilter()
        queries = [queries] if isinstance(queries, str) else [q for q in queries if q.strip()]
        k = k or cfg.top_k
        cands = self.candidates(queries, f, cfg)
        if not cands:
            return []
        ranked = sorted(cands.values(), key=lambda h: -h.score)
        pool = ranked[: max(cfg.rerank_candidates if reranker else 0, k * 4, 40)]
        pool = self.hydrate(pool)
        if reranker is not None:
            reranker.rerank(rerank_query or queries[0], pool[: cfg.rerank_candidates])
        return self.select(pool, k, cfg)

    def rank_documents(
        self, queries: list[str], f: SearchFilter, cfg: RetrievalSettings, per_query_k: int, top_docs: int,
        query_stats: list[dict] | None = None,
    ) -> list[dict]:
        """Dokumentebene: Treffer je Dokument zusammenzählen (für den Forschungsstand).
        query_stats (optional) erhält je Suchanfrage, wie viele der ausgewählten Texte sie gefunden hat
        und wie viele nur sie gefunden hat."""
        per_query: list[set[int]] = []
        cands = self.candidates(queries, f, cfg, candidate_k=per_query_k, per_query=per_query)
        rows = self.store.chunk_rows(cands.keys())
        docs: dict[tuple[str, str], dict] = {}
        for cid, h in cands.items():
            row = rows.get(cid)
            if not row:
                continue
            key = (row["lib"], row["item_key"])
            d = docs.setdefault(key, {"lib": key[0], "item_key": key[1], "score": 0.0, "hits": 0, "best": []})
            d["score"] += h.score
            d["hits"] += 1
            d["best"].append((h.score, cid))
        ranked = sorted(docs.values(), key=lambda d: -d["score"])[:top_docs]
        for d in ranked:
            d["best"] = [cid for _, cid in sorted(d["best"], reverse=True)[:3]]
        if query_stats is not None:
            selected = {(d["lib"], d["item_key"]) for d in ranked}
            doc_sets = [{(rows[c]["lib"], rows[c]["item_key"]) for c in ids if c in rows} & selected
                        for ids in per_query]
            query_stats[:] = []
            for i, q in enumerate(queries):
                others = set().union(*(s for j, s in enumerate(doc_sets) if j != i)) if len(doc_sets) > 1 else set()
                mine = doc_sets[i] if i < len(doc_sets) else set()
                query_stats.append({"query": q, "docs": len(mine), "unique": len(mine - others)})
        return ranked
