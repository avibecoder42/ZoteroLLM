"""Quellenaufbereitung: nummerierte Textstellen für das LLM und Links nach Zotero."""

from __future__ import annotations

from dataclasses import dataclass

from zotivity.extract.chunker import estimate_tokens
from zotivity.index.store import Store, strip_bidi
from zotivity.retrieval.search import Hit
from zotivity.zotero import opens_in_reader, zotero_open_pdf_url, zotero_select_url


def author_year(item: dict) -> str:
    who = strip_bidi(item.get("creator_summary"))
    if not who:
        creators = item.get("creators") or []
        if creators:
            c = creators[0]
            who = c.get("lastName") or c.get("name") or ""
            if len(creators) == 2:
                c2 = creators[1]
                who += " & " + (c2.get("lastName") or c2.get("name") or "")
            elif len(creators) > 2:
                who += " et al."
    year = item.get("year") or "o. J."
    return f"{who or 'o. A.'} {year}".strip()


@dataclass
class Source:
    n: int
    chunk_id: int
    lib: str
    item_key: str
    att_key: str
    title: str
    citation: str  # "Müller et al. 2021"
    page_label: str
    page_index: int | None
    text: str
    kind: str
    score: float
    relevance: dict | None = None
    content_type: str = ""  # Dateityp des Anhangs; „PDF öffnen“ nur, wenn Zotero ihn selbst anzeigt

    @property
    def page_text(self) -> str:
        return f"S. {self.page_label}" if self.page_label else ""

    def header(self) -> str:
        parts = [f"[{self.n}] {self.citation}: {self.title}"]
        if self.page_label:
            parts.append(f"({self.page_text})")
        if self.kind == "abstract":
            parts.append("(Abstract)")
        return " ".join(parts)

    def as_dict(self) -> dict:
        d = {
            "n": self.n, "chunk_id": self.chunk_id, "lib": self.lib, "item_key": self.item_key,
            "att_key": self.att_key, "title": self.title, "citation": self.citation,
            "page_label": self.page_label, "page_index": self.page_index, "text": self.text,
            "kind": self.kind, "score": round(self.score, 5), "relevance": self.relevance,
            "zotero_select": zotero_select_url(self.lib, self.item_key),
        }
        if self.att_key and opens_in_reader(self.content_type):
            d["zotero_pdf"] = zotero_open_pdf_url(self.lib, self.att_key, self.page_index)
        return d


LEVELS = {5: "sehr hoch", 4: "hoch", 3: "mittel", 2: "eher gering", 1: "gering"}


def _level(value: float, thresholds: tuple[float, ...]) -> int:
    for level, t in zip((5, 4, 3, 2), thresholds):
        if value >= t:
            return level
    return 1


def relevance_info(h: Hit, best_vector: float | None, best_keyword: float | None, rank: int, total: int) -> dict:
    """Relevanz einer Textstelle für die Anzeige. Keine Wahrscheinlichkeit: gemessen am besten Treffer der Frage,
    ausser die Neusortierung liefert einen eigenen Wert (0–1)."""
    info = {"rank": rank, "of": total, "vector": None if h.vector_score is None else round(h.vector_score, 3),
            "best_vector": None if best_vector is None else round(best_vector, 3),
            "keyword": h.keyword_score is not None, "rerank": None}
    if h.rerank_relevance is not None:
        info.update(basis="rerank", rerank=round(h.rerank_relevance, 3),
                    level=_level(h.rerank_relevance, (0.8, 0.6, 0.4, 0.2)))
    elif h.vector_score is not None and best_vector and best_vector > 0:
        ratio = h.vector_score / best_vector
        info.update(basis="vector", level=_level(ratio, (0.96, 0.9, 0.82, 0.72)))
    elif h.keyword_score is not None and best_keyword:
        ratio = h.keyword_score / best_keyword
        info.update(basis="keyword", level=_level(ratio, (2.0, 0.9, 0.7, 0.5)))  # nur Stichworte: höchstens „hoch“
    else:
        info.update(basis="rank", level=3)
    info["label"] = LEVELS[info["level"]]
    return info


def build_sources(store: Store, hits: list[Hit], neighbor_chunks: int, token_budget: int) -> list[Source]:
    sources: list[Source] = []
    used = 0
    best_vector = max((h.vector_score for h in hits if h.vector_score is not None), default=None)
    best_keyword = max((h.keyword_score for h in hits if h.keyword_score is not None), default=None)
    for h in hits:
        c = h.chunk
        text = c["text"]
        if neighbor_chunks and c.get("att_key"):
            neigh = store.neighbor_chunks(c["lib"], c["att_key"], c["ord"], neighbor_chunks)
            neigh = [x for x in neigh if x["kind"] == "text" or x["id"] == c["id"]]
            if neigh:
                text = _merge_overlapping([x["text"] for x in neigh])
        tokens = estimate_tokens(text)
        if sources and used + tokens > token_budget:
            break
        used += tokens
        att = store.attachment(c["lib"], c["att_key"]) if c.get("att_key") else None
        sources.append(Source(
            n=len(sources) + 1, chunk_id=c["id"], lib=c["lib"], item_key=c["item_key"], att_key=c.get("att_key") or "",
            title=h.item.get("title") or "(ohne Titel)", citation=author_year(h.item),
            page_label=c.get("page_label") or "", page_index=c.get("page_start"), text=text, kind=c.get("kind", "text"),
            score=h.rerank_score if h.rerank_score is not None else h.score,
            relevance=relevance_info(h, best_vector, best_keyword, len(sources) + 1, len(hits)),
            content_type=(att or {}).get("content_type") or "",
        ))
    for s in sources:
        s.relevance["of"] = len(sources)
    return sources


def _merge_overlapping(texts: list[str]) -> str:
    """Verkettet Nachbarabschnitte und entfernt die Überlappung."""
    out = texts[0]
    for t in texts[1:]:
        overlap = 0
        for size in range(min(len(out), len(t), 800), 20, -1):
            if out.endswith(t[:size]):
                overlap = size
                break
        out += ("" if overlap else " ") + t[overlap:]
    return out


def format_sources(sources: list[Source]) -> str:
    return "\n\n".join(f"{s.header()}\n{s.text}" for s in sources)
