"""Vergleichsmodus: dieselbe Frage mit zwei Embedding-Modellen (reine Bedeutungssuche), Treffer nebeneinander.

Hilft beim Entscheid, welches Modell zur eigenen Bibliothek passt. Beide Modelle brauchen einen Index; wie
weit er reicht, zeigt die Abdeckung (eingebettete Abschnitte im gewählten Bereich).
"""

from __future__ import annotations

import json

from zotivity.embeddings import make_embedder
from zotivity.index.store import strip_bidi
from zotivity.index.vectors import VectorIndex
from zotivity.settings import EmbeddingSettings


def embedder_for_space(engine, space: dict):
    """Embedder, der Suchanfragen in denselben Vektorraum bringt wie die gespeicherten Abschnitte."""
    current = engine.settings.embedding
    params = json.loads(space["params"] or "{}")
    cfg = {"provider": space["provider"], "model": space["model"],
           "query_prefix": params.get("query_prefix", ""), "document_prefix": params.get("document_prefix", "")}
    if space["provider"] == current.provider:
        cfg.update(base_url=current.base_url, num_thread=current.num_thread, parallel=current.parallel,
                   keep_alive_minutes=current.keep_alive_minutes)
    if space["provider"] == "builtin":
        cfg["dimensions"] = int(space["dim"])
    elif space["provider"] == current.provider and space["model"] == current.model:
        cfg["dimensions"] = current.dimensions
    return make_embedder(EmbeddingSettings.model_validate(cfg))


def _side(engine, space: dict, query: str, allowed, k: int) -> dict:
    emb = embedder_for_space(engine, space)
    warning = None
    if emb.space_id != space["space"]:
        warning = "Die Einstellungen dieses Modells haben sich geändert – die Treffer sind nur bedingt vergleichbar."
    active_space, vindex = None, None
    if engine.vector_index_if_loaded() is not None:
        active_space, vindex = engine.vector_index()
    if active_space != space["space"]:
        ids, mat = engine.store.load_vectors(space["space"], int(space["dim"]))
        vindex = VectorIndex(int(space["dim"]))
        vindex.load(ids, mat)
    qv = emb.embed_query(query)
    raw = vindex.search(qv, k * 4, allowed)
    rows = engine.store.chunk_rows([cid for cid, _ in raw])
    items = engine.store.items({(r["lib"], r["item_key"]) for r in rows.values()})
    hits, per_doc = [], {}
    for cid, score in raw:
        row = rows.get(cid)
        if not row:
            continue
        key = (row["lib"], row["item_key"])
        if per_doc.get(key, 0) >= 2:
            continue
        per_doc[key] = per_doc.get(key, 0) + 1
        it = items.get(key) or {}
        hits.append({"chunk_id": cid, "score": round(score, 4), "lib": key[0], "item_key": key[1],
                     "title": it.get("title") or "", "creators": strip_bidi(it.get("creator_summary") or ""),
                     "year": it.get("year"), "page": row.get("page_label") or row.get("page_start"),
                     "kind": row.get("kind"), "text": (row.get("text") or "")[:400]})
        if len(hits) >= k:
            break
    n_scope = len(allowed) if allowed is not None else engine.store.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    covered = vindex.count_in(allowed)
    return {"space": space["space"], "provider": space["provider"], "model": space["model"], "dim": space["dim"],
            "hits": hits, "coverage": {"embedded": covered, "chunks": int(n_scope)}, "warning": warning}


def compare(engine, query: str, space_a: str, space_b: str, filters: dict | None = None, k: int = 10) -> dict:
    spaces = {s["space"]: s for s in engine.store.spaces()}
    missing = [s for s in (space_a, space_b) if s not in spaces]
    if missing:
        raise ValueError("Für eines der Modelle gibt es keinen Index.")
    from zotivity.retrieval.search import Searcher

    f = engine.make_filter(filters or {})
    allowed = Searcher(engine)._allowed_ids(f)
    a = _side(engine, spaces[space_a], query, allowed, k)
    b = _side(engine, spaces[space_b], query, allowed, k)
    docs_a = {(h["lib"], h["item_key"]) for h in a["hits"]}
    docs_b = {(h["lib"], h["item_key"]) for h in b["hits"]}
    for side, other in ((a, docs_b), (b, docs_a)):
        for h in side["hits"]:
            h["shared"] = (h["lib"], h["item_key"]) in other
    return {"query": query, "a": a, "b": b, "shared_docs": len(docs_a & docs_b),
            "docs": {"a": len(docs_a), "b": len(docs_b)}}
