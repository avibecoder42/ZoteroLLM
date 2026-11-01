"""Vektorsuche im Arbeitsspeicher (exakte Kosinus-Ähnlichkeit mit NumPy).

Für 100'000–200'000 Abschnitte genügt die exakte Suche: einige 10 ms pro Anfrage.
Die Vektoren liegen als float16 vor (halber Speicher), gerechnet wird blockweise
in float32. Die Klasse kapselt die Suche, damit später bei Bedarf ein ANN-Index
(z. B. HNSW) eingesetzt werden kann, ohne den Rest zu ändern.
"""

from __future__ import annotations

import threading

import numpy as np

BLOCK = 65536


def normalize(vecs: np.ndarray) -> np.ndarray:
    vecs = np.asarray(vecs, dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs[None, :]
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


class VectorIndex:
    def __init__(self, dim: int):
        self.dim = dim
        self._lock = threading.RLock()
        self._ids = np.zeros(0, dtype=np.int64)
        self._mat = np.zeros((0, dim), dtype=np.float16)
        self._pending_ids: list[np.ndarray] = []
        self._pending_vecs: list[np.ndarray] = []
        self._deleted: set[int] = set()

    def __len__(self) -> int:
        with self._lock:
            return len(self._ids) + sum(len(x) for x in self._pending_ids) - len(self._deleted)

    def load(self, ids: np.ndarray, mat: np.ndarray) -> None:
        order = np.argsort(ids)
        with self._lock:
            self._ids = np.asarray(ids, dtype=np.int64)[order]
            self._mat = np.asarray(mat, dtype=np.float16)[order]
            self._pending_ids.clear()
            self._pending_vecs.clear()
            self._deleted.clear()

    def add(self, ids: list[int], vecs: np.ndarray) -> None:
        """Neue (normalisierte) Vektoren, z. B. während des Indexierens."""
        if len(ids) == 0:
            return
        with self._lock:
            self._pending_ids.append(np.asarray(ids, dtype=np.int64))
            self._pending_vecs.append(np.asarray(vecs, dtype=np.float16))
            self._deleted.difference_update(int(i) for i in ids)
            if sum(len(x) for x in self._pending_ids) > 20000:
                self._compact()

    def remove(self, ids) -> None:
        with self._lock:
            self._deleted.update(int(i) for i in ids)

    def _compact(self) -> None:
        ids = np.concatenate([self._ids, *self._pending_ids])
        mat = np.concatenate([self._mat, *self._pending_vecs]) if self._pending_vecs else self._mat
        # Bei doppelten IDs gewinnt der neueste Vektor
        _, last = np.unique(ids[::-1], return_index=True)
        keep = len(ids) - 1 - last
        if self._deleted:
            deleted = np.fromiter(self._deleted, dtype=np.int64)
            keep = keep[~np.isin(ids[keep], deleted)]
        keep.sort()
        order = np.argsort(ids[keep])
        self._ids = ids[keep][order]
        self._mat = mat[keep][order]
        self._pending_ids.clear()
        self._pending_vecs.clear()
        self._deleted.clear()

    def search(
        self, query: np.ndarray, k: int, allowed_ids: np.ndarray | None = None
    ) -> list[tuple[int, float]]:
        """Top-k (chunk_id, Kosinus) – optional nur innerhalb erlaubter IDs."""
        with self._lock:
            if self._pending_ids or self._deleted:
                self._compact()
            ids, mat = self._ids, self._mat
        if len(ids) == 0 or k <= 0:
            return []
        q = normalize(query)[0]
        if allowed_ids is not None:
            pos = np.nonzero(np.isin(ids, allowed_ids))[0]
            if len(pos) == 0:
                return []
            sub_ids = ids[pos]
            scores = (mat[pos].astype(np.float32) @ q)
        else:
            sub_ids = ids
            scores = np.empty(len(ids), dtype=np.float32)
            for start in range(0, len(ids), BLOCK):
                block = mat[start : start + BLOCK].astype(np.float32)
                scores[start : start + BLOCK] = block @ q
        k = min(k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(sub_ids[i]), float(scores[i])) for i in top]

    def count_in(self, allowed_ids: np.ndarray | None) -> int:
        """Wie viele der erlaubten Abschnitte einen Vektor haben (Abdeckung des Index)."""
        with self._lock:
            if self._pending_ids or self._deleted:
                self._compact()
            ids = self._ids
        return len(ids) if allowed_ids is None else int(np.isin(ids, allowed_ids).sum())

    def vectors_for(self, ids: list[int]) -> dict[int, np.ndarray]:
        with self._lock:
            if self._pending_ids or self._deleted:
                self._compact()
            all_ids, mat = self._ids, self._mat
        want = np.asarray(sorted(set(ids)), dtype=np.int64)
        pos = np.searchsorted(all_ids, want)
        out: dict[int, np.ndarray] = {}
        for w, p in zip(want, pos):
            if p < len(all_ids) and all_ids[p] == w:
                out[int(w)] = mat[p].astype(np.float32)
        return out
