"""Abbild der Zotero-Bibliotheken: eigene Bibliothek und alle Gruppen mit (Unter-)Sammlungen."""

from __future__ import annotations

import logging

from zotivity.i18n import tr
from zotivity.index.store import strip_bidi
from zotivity.zotero.client import ZoteroError, ZoteroUnavailable

log = logging.getLogger(__name__)

USER_LIB = "users/0"
USER_LIB_NAME = "Meine Bibliothek"


def lib_label(lib: str, name: str | None = None) -> str:
    """Anzeigename einer Bibliothek; die eigene heisst je nach Sprache der Oberfläche anders."""
    return tr(USER_LIB_NAME) if lib == USER_LIB else (name or lib)


def _nest(lib: str, rows: list[dict]) -> list[dict]:
    """Flache Sammlungsliste (lib, key, name, parent, num_items) → Baum, alphabetisch wie in Zotero."""
    nodes = {r["key"]: {"id": f"{lib}:{r['key']}", "key": r["key"], "name": r["name"],
                        "num_items": r.get("num_items"), "children": []} for r in rows}
    roots = []
    for r in rows:
        node = nodes[r["key"]]
        parent = nodes.get(r.get("parent") or "")
        (parent["children"] if parent else roots).append(node)

    def sort(nodes_):
        nodes_.sort(key=lambda n: n["name"].casefold())
        for n in nodes_:
            sort(n["children"])

    sort(roots)
    return roots


def fetch_tree(engine) -> dict:
    """Live aus Zotero (und im Index zwischengespeichert); ohne Zotero der letzte bekannte Stand."""
    store = engine.store
    zot = engine.zotero()
    try:
        if not zot.is_available():
            raise ZoteroUnavailable("Zotero ist nicht erreichbar.")
        libs = [(USER_LIB, USER_LIB_NAME, "user")]
        groups = sorted(((f"groups/{g['id']}", g["data"].get("name", ""), "group") for g in zot.groups()),
                        key=lambda x: x[1].casefold())
        libs += groups
        out = []
        for lib, name, typ in libs:
            cols = zot.collections(lib)
            store.replace_collections(lib, cols)
            if store.library_state(lib).get("name") != name:
                store.set_library_state(lib, name=name)
            out.append({"lib": lib, "id": f"{lib}:*", "name": lib_label(lib, name), "type": typ,
                        "num_items": zot.count_top_items(lib), "collections": _nest(lib, store.collections(lib))})
        return {"online": True, "libraries": out}
    except ZoteroError as e:
        log.info("Zotero-Baum aus dem Zwischenspeicher: %s", e)
        names = store.library_names()
        libs = sorted({c["lib"] for c in store.collections()} | set(names), key=lambda lib: (
            lib != USER_LIB, (names.get(lib) or lib).casefold()))
        out = [{"lib": lib, "id": f"{lib}:*", "name": lib_label(lib, names.get(lib)),
                "type": "user" if lib == USER_LIB else "group", "num_items": None,
                "collections": _nest(lib, store.collections(lib))} for lib in libs]
        return {"online": False, "message": str(e), "libraries": out}


def describe_sources(engine, sources: list[str]) -> list[dict]:
    """Quellen eines Korpus lesbar machen: [{id, label, path}]."""
    store = engine.store
    names = store.library_names()
    cols = {(c["lib"], c["key"]): c for c in store.collections()}
    out = []
    for s in sources:
        lib, _, key = s.partition(":")
        lib_name = lib_label(lib, names.get(lib))
        if key == "*":
            out.append({"id": s, "label": lib_name, "path": tr("ganze Bibliothek"), "kind": "library"})
            continue
        if key.startswith("@"):  # einzelner Eintrag
            item = store.item(lib, key[1:])
            label = (item or {}).get("title") or key[1:]
            who = strip_bidi((item or {}).get("creator_summary") or "")
            year = (item or {}).get("year") or ""
            out.append({"id": s, "label": label if len(label) <= 60 else label[:57] + " …",
                        "path": f"{lib_name} · {who} {year}".strip(), "kind": "item", "missing": item is None})
            continue
        parts = []
        node = cols.get((lib, key))
        label = node["name"] if node else key
        while node and node.get("parent"):
            node = cols.get((lib, node["parent"]))
            if node:
                parts.insert(0, node["name"])
        out.append({"id": s, "label": label, "path": " › ".join([lib_name, *parts]), "kind": "collection",
                    "missing": (lib, key) not in cols})
    return out
