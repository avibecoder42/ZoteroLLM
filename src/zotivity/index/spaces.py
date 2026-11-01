"""Gespeicherte Indizes (Vektorräume) zwischen Embedding-Anbietern übernehmen.

Dasselbe Modell liefert bei Ollama und in der eingebauten Laufzeit praktisch dieselben Vektoren (gleiche
GGUF-Gewichte, ggf. andere Genauigkeit). Statt die ganze Bibliothek neu einzubetten, prüft Zotivity an einer
Stichprobe, ob die Vektoren übereinstimmen, und übernimmt dann den bestehenden Index.
"""

from __future__ import annotations

import json
import re

import numpy as np

from zotivity.embeddings import model_catalog
from zotivity.index.vectors import normalize

# Mittlere bzw. kleinste Kosinus-Ähnlichkeit, ab der zwei Räume als gleich gelten
MIN_MEAN, MIN_ANY = 0.99, 0.97


def _norm_name(model: str) -> str:
    name = model.lower().split("/")[-1].removesuffix(":latest")
    return re.sub(r"[-_.]?(gguf|q\d\w*|f16|bf16)$", "", name)


def same_model(space: dict, emb) -> bool:
    """Gehört ein gespeicherter Raum zum selben Modell wie der Embedder (über Katalog-Aliasse oder Namen)?"""
    if space["provider"] == emb.provider and space["model"] == emb.model:
        return True
    target = model_catalog.get(emb.model) if emb.provider == "builtin" else model_catalog.match_alias(emb.model)
    other = model_catalog.get(space["model"]) if space["provider"] == "builtin" else model_catalog.match_alias(space["model"])
    if target is not None and other is not None:
        return target.id == other.id
    return _norm_name(space["model"]) == _norm_name(emb.model)


def candidates(engine, emb) -> list[dict]:
    """Andere Räume desselben Modells mit gleicher Dimension und gleichen Präfixen, die Vektoren enthalten."""
    active = emb.space_id
    out = []
    for s in engine.store.spaces():
        if s["space"] == active or not s["n"] or int(s["dim"] or 0) != emb.dim:
            continue
        params = json.loads(s["params"] or "{}")
        if (params.get("query_prefix", "") != emb.query_prefix
                or params.get("document_prefix", "") != emb.document_prefix):
            continue
        if same_model(s, emb):
            out.append(s)
    return out


def check(engine, source_space: str, emb, sample: int = 24) -> dict:
    """Stichprobe neu einbetten und mit den gespeicherten Vektoren vergleichen."""
    from zotivity.index.indexer import embedding_text

    store = engine.store
    rows = store.con.execute(
        "SELECT chunk_id, vec FROM embeddings WHERE space=? ORDER BY RANDOM() LIMIT ?", (source_space, sample)
    ).fetchall()
    if not rows:
        return {"compatible": False, "n": 0, "reason": "Der Index enthält keine Vektoren."}
    ids = [r[0] for r in rows]
    old = {r[0]: np.frombuffer(r[1], dtype=np.float16).astype(np.float32) for r in rows}
    chunks = store.chunk_rows(ids)
    items = store.items({(c["lib"], c["item_key"]) for c in chunks.values()})
    header = engine.settings.chunking.metadata_header
    ids = [i for i in ids if i in chunks]
    texts = [embedding_text(chunks[i], items.get((chunks[i]["lib"], chunks[i]["item_key"])), header) for i in ids]
    new = normalize(emb.embed_documents(texts))
    old_m = normalize(np.vstack([old[i] for i in ids]))
    if new.shape != old_m.shape:
        return {"compatible": False, "n": len(ids), "reason": "Die Dimension der Vektoren unterscheidet sich."}
    cos = (new * old_m).sum(axis=1)
    mean, low = float(cos.mean()), float(cos.min())
    return {"compatible": mean >= MIN_MEAN and low >= MIN_ANY, "n": len(ids), "cos_mean": round(mean, 4),
            "cos_min": round(low, 4)}


def adopt(engine, source_space: str, emb) -> dict:
    """Vektoren des Quellraums in den Raum des Embedders verschieben (kein zweites Mal Speicherplatz)."""
    target = emb.space_id
    store = engine.store
    store.ensure_space(target, emb.provider, emb.model, emb.dim, emb.space_params)
    with store.write() as con:
        moved = con.execute("UPDATE OR IGNORE embeddings SET space=? WHERE space=?", (target, source_space)).rowcount
        con.execute("DELETE FROM embeddings WHERE space=?", (source_space,))
        con.execute("DELETE FROM spaces WHERE space=?", (source_space,))
    engine.reset_vector_index()
    return {"moved": moved, "space": target}
