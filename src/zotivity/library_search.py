"""Suche in der Zotero-Bibliothek ohne Sprachmodell: Einfeld- und Mehrfeldsuche über die Metadaten aller
Bibliotheken (eigene und Gruppen), Filter nach Jahr, Eintragsart, Bibliothek, Sammlung, PDF/Index, dazu
Volltextsuche in den indexierten Texten. Grundlage ist der lokale Suchkatalog (Abgleich mit Zotero).

Suchsprache je Feld: Wörter werden UND-verknüpft und als Wortanfang gesucht („digit“ findet „digital“),
"genaue Phrase" in Anführungszeichen, -wort schliesst aus, ODER/OR verbindet Alternativen.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from zotivity.index.store import SearchFilter, Store, strip_bidi
from zotivity.zotero import zotero_open_pdf_url, zotero_select_url
from zotivity.zotero.tree import USER_LIB, lib_label

FIELDS = {"title": "title", "creator": "creator_names", "publication": "publication", "abstract": "abstract",
          "tags": "tags", "doi": "doi"}
SORTS = {
    "relevance": None,
    "year_desc": "i.year IS NULL, i.year DESC, i.title COLLATE NOCASE",
    "year_asc": "i.year IS NULL, i.year ASC, i.title COLLATE NOCASE",
    "title": "i.title COLLATE NOCASE",
    "creator": "i.creator_summary COLLATE NOCASE, i.year",
}
MARK_START, MARK_END = "\u0001", "\u0002"
_TOKEN = re.compile(r'(-?)"([^"]+)"|(\S+)')


def fts_expression(text: str) -> str | None:
    """Eingabe → FTS5-Ausdruck. None, wenn nichts Suchbares übrig bleibt."""
    positives: list[str] = []
    negatives: list[str] = []
    pending_or = False
    for m in _TOKEN.finditer(text or ""):
        neg_phrase, phrase, word = m.group(1), m.group(2), m.group(3)
        if word and word.upper() in ("OR", "ODER", "|"):
            pending_or = bool(positives)
            continue
        if word and word.upper() in ("AND", "UND"):
            continue
        neg = bool(neg_phrase) or bool(word and word.startswith("-") and len(word) > 1)
        if phrase is not None:
            terms = re.findall(r"[\w]+", phrase.lower())
            if not terms:
                continue
            expr = '"' + " ".join(terms) + '"'
        else:
            w = word.lstrip("-").lower()
            terms = re.findall(r"[\w]+", w)
            if not terms:
                continue
            # Wortanfang: „digit“ findet „digital“, „digitale“ …; Bindestrich-Wörter als Phrase
            expr = ('"' + " ".join(terms) + '"') if len(terms) > 1 else f'"{terms[0]}"*'
        if neg:
            negatives.append(expr)
        elif pending_or and positives:
            positives[-1] = f"({positives[-1]} OR {expr})"
            pending_or = False
        else:
            positives.append(expr)
    if not positives:
        return None
    out = " AND ".join(positives)
    for n in negatives:
        out = f"({out}) NOT {n}"
    return out


@dataclass
class CatalogQuery:
    q: str = ""
    title: str = ""
    creator: str = ""
    publication: str = ""
    abstract: str = ""
    tags: str = ""
    doi: str = ""
    fulltext: str = ""
    year_from: int | None = None
    year_to: int | None = None
    item_types: list[str] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)  # "lib:KEY" inkl. Untersammlungen
    has_pdf: bool = False
    indexed: bool = False
    sort: str = "relevance"
    limit: int = 100
    offset: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> CatalogQuery:
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__ and v not in (None, "")}
        q = cls(**known)
        q.limit = max(1, min(int(q.limit), 500))
        q.offset = max(0, int(q.offset))
        if q.sort not in SORTS:
            q.sort = "relevance"
        return q


def search_signature(query: CatalogQuery) -> dict:
    """Was eine Suche ausmacht – ohne Seite, Menge und Sortierung, nur gesetzte Felder."""
    out = {}
    for name in query.__dataclass_fields__:
        if name in ("limit", "offset", "sort"):
            continue
        v = getattr(query, name)
        if isinstance(v, str):
            v = v.strip()
        if v not in (None, "", [], False):
            out[name] = v
    return out


def remember_search(store: Store, project_id: int, query: CatalogQuery, total: int) -> int | None:
    """Ausgeführte Suche in den Verlauf des Projekts (alle Suchen; dieselbe Suche nur einmal, zuoberst)."""
    sig = search_signature(query)
    if not sig:
        return None
    return store.remember_search(project_id, sig, query.sort, total)


def search_catalog(store: Store, query: CatalogQuery) -> dict:
    con = store.con
    meta_parts: list[str] = []
    expr = fts_expression(query.q)
    if expr:
        meta_parts.append(f"({expr})")
    for name, col in FIELDS.items():
        e = fts_expression(getattr(query, name))
        if e:
            meta_parts.append(f"{col} : ({e})")
    where, params = ["i.item_type NOT IN ('note', 'annotation')"], []
    joins = ""
    rank = "0"
    if meta_parts:
        joins += " JOIN items_fts ON items_fts.rowid = i.rowid"
        where.append("items_fts MATCH ?")
        params.append(" AND ".join(meta_parts))
        rank = "bm25(items_fts, 10.0, 6.0, 3.0, 1.5, 4.0, 2.0)"
    if query.year_from:
        where.append("i.year >= ?")
        params.append(int(query.year_from))
    if query.year_to:
        where.append("i.year <= ?")
        params.append(int(query.year_to))
    if query.item_types:
        where.append(f"i.item_type IN ({','.join('?' * len(query.item_types))})")
        params += list(query.item_types)
    if query.libraries:
        where.append(f"i.lib IN ({','.join('?' * len(query.libraries))})")
        params += list(query.libraries)
    if query.has_pdf:
        where.append("EXISTS (SELECT 1 FROM attachments a WHERE a.lib=i.lib AND a.parent=i.key"
                     " AND a.content_type='application/pdf')")
    if query.indexed:
        where.append("EXISTS (SELECT 1 FROM attachments a WHERE a.lib=i.lib AND a.parent=i.key AND a.status='indexed')")

    # Sammlungen (inkl. Untersammlungen) und Volltext: als Menge erlaubter Einträge
    allowed: set[tuple[str, str]] | None = None
    if query.collections:
        allowed = store.allowed_items(SearchFilter(collections=list(query.collections))) or set()
    snippets: dict[tuple[str, str], str] = {}
    fulltext_hits = 0
    ft = fts_expression(query.fulltext)
    if ft:
        rows = con.execute(
            "SELECT c.lib, c.item_key, snippet(chunks_fts, 0, ?, ?, '…', 14) AS snip, bm25(chunks_fts) AS s"
            " FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid"
            " WHERE chunks_fts MATCH ? AND c.kind != 'references' ORDER BY s LIMIT 5000",
            (MARK_START, MARK_END, ft)).fetchall()
        found: set[tuple[str, str]] = set()
        for r in rows:
            k = (r["lib"], r["item_key"])
            if k not in snippets:
                snippets[k] = r["snip"]
            found.add(k)
        fulltext_hits = len(found)
        allowed = found if allowed is None else allowed & found
    if allowed is not None:
        con.execute("CREATE TEMP TABLE IF NOT EXISTS _search_allowed(lib TEXT, key TEXT)")
        con.execute("DELETE FROM _search_allowed")
        con.executemany("INSERT INTO _search_allowed VALUES(?,?)", list(allowed))
        joins += " JOIN _search_allowed sa ON sa.lib = i.lib AND sa.key = i.key"

    if not meta_parts and not ft and not any([query.year_from, query.year_to, query.item_types, query.libraries,
                                                query.collections, query.has_pdf, query.indexed]):
        return {"total": 0, "results": [], "empty_query": True}

    base = f"FROM items i{joins} WHERE {' AND '.join(where)}"
    total = con.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    order = SORTS[query.sort] or (f"{rank}, i.year DESC" if meta_parts else "i.year IS NULL, i.year DESC")
    rows = con.execute(f"SELECT i.*, {rank} AS rank {base} ORDER BY {order} LIMIT ? OFFSET ?",
                       params + [query.limit, query.offset]).fetchall()
    if allowed is not None:
        con.execute("DELETE FROM _search_allowed")
    results = enrich(store, [dict(r) for r in rows])
    for r in results:
        snip = snippets.get((r["lib"], r["key"]))
        if snip:
            r["snippet"] = snip
    return {"total": total, "results": results, "fulltext_documents": fulltext_hits if ft else None}


def library_names(store: Store) -> dict[str, str]:
    names = store.library_names()
    names[USER_LIB] = lib_label(USER_LIB)
    return names


def enrich(store: Store, rows: list[dict]) -> list[dict]:
    """Fundort in Zotero (Bibliothek, Sammlungspfade), Anhänge, Index-Status, Links."""
    if not rows:
        return []
    names = library_names(store)
    cols = {(c["lib"], c["key"]): c for c in store.collections()}

    def path(lib: str, key: str) -> list[str]:
        parts, node, seen = [], cols.get((lib, key)), set()
        while node and node["key"] not in seen:
            seen.add(node["key"])
            parts.insert(0, node["name"])
            node = cols.get((lib, node["parent"])) if node.get("parent") else None
        return parts

    atts: dict[tuple[str, str], list[dict]] = {}
    keys = [(r["lib"], r["key"]) for r in rows]
    for i in range(0, len(keys), 400):
        batch = keys[i:i + 400]
        q = " OR ".join(["(lib=? AND parent=?)"] * len(batch))
        for a in store.con.execute(f"SELECT lib, key, parent, title, content_type, status, error, n_pages FROM attachments"
                                   f" WHERE {q}", [x for p in batch for x in p]):
            atts.setdefault((a["lib"], a["parent"]), []).append(dict(a))
    out = []
    for r in rows:
        lib, key = r["lib"], r["key"]
        coll_keys = json.loads(r.get("collections") or "[]")
        locations = [{"label": names.get(lib, lib), "path": names.get(lib, lib), "kind": "library",
                      "select": zotero_select_url(lib, key)}]
        for ck in coll_keys:
            p = path(lib, ck)
            if p:
                locations.append({"label": p[-1], "path": " › ".join([names.get(lib, lib), *p]), "kind": "collection",
                                  "collection": f"{lib}:{ck}", "select": zotero_select_url(lib, key, ck)})
        files = sorted(atts.get((lib, key), []), key=lambda a: (a["content_type"] != "application/pdf", a["key"]))
        pdf = next((a for a in files if a["content_type"] == "application/pdf"), None)
        status = "indexed" if any(a["status"] == "indexed" for a in files) else (
            "pending" if any(a["status"] == "pending" for a in files) else
            "problem" if any(a["status"] in ("error", "no_text") for a in files) else "none")
        creators = json.loads(r.get("creators") or "[]")
        out.append({
            "lib": lib, "key": key, "library": names.get(lib, lib), "group": lib.startswith("groups/"),
            "title": r.get("title") or "", "creators": strip_bidi(r.get("creator_summary") or "")
            or ", ".join(c.get("lastName") or c.get("name") or "" for c in creators[:3]),
            "year": r.get("year"), "item_type": r.get("item_type"), "publication": r.get("publication") or "",
            "doi": r.get("doi") or "", "locations": locations, "collections": [x["collection"] for x in locations[1:]],
            "attachments": [{"key": a["key"], "content_type": a["content_type"], "status": a["status"],
                             "pages": a["n_pages"]} for a in files],
            "index_status": status, "select": zotero_select_url(lib, key),
            "pdf": zotero_open_pdf_url(lib, pdf["key"]) if pdf else None,
        })
    return out


def facets(store: Store) -> dict:
    """Werte für die Filter: Bibliotheken, Eintragsarten, Jahresspanne."""
    names = library_names(store)
    libs = [{"lib": r["lib"], "name": names.get(r["lib"], r["lib"]), "items": r["n"]} for r in store.con.execute(
        "SELECT lib, COUNT(*) AS n FROM items WHERE item_type NOT IN ('note','annotation') GROUP BY lib")]
    libs.sort(key=lambda x: (x["lib"] != USER_LIB, x["name"].casefold()))
    types = [{"type": r["item_type"], "items": r["n"]} for r in store.con.execute(
        "SELECT item_type, COUNT(*) AS n FROM items WHERE item_type NOT IN ('note','annotation')"
        " GROUP BY item_type ORDER BY n DESC")]
    years = store.con.execute("SELECT MIN(year), MAX(year) FROM items WHERE year IS NOT NULL").fetchone()
    return {"libraries": libs, "item_types": types, "years": [years[0], years[1]]}
