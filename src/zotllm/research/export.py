"""Übergabe der Auswahl an Zotero, je Zielordner (Konzept 3.2, Ansicht 7).

Zuerst ein Plan (liest nur): was neu angelegt wird, was schon in der Bibliothek ist und nur in den Ordner kommt, was
schon übergeben wurde, welche Sammlungen fehlen. Geschrieben wird nur mit ``confirm=True`` – die Oberfläche fragt
vorher ausdrücklich nach. Angaben werden vorher über Crossref vervollständigt (wenn eine DOI da ist).
"""

from __future__ import annotations

from collections.abc import Callable

from .errors import ResearchError, ZoteroWriteRefused
from .pool import sources_of
from .ports import ZoteroPort
from .records import short_ref
from .sources import source_label
from .sources.crossref import Crossref, enrich
from .store import Store
from .zotero_items import to_zotero

# Ordner, in die das Screening aufnimmt: feste Nummern (Kürzel 1–9 für die ersten neun), Lücken nach dem Löschen bleiben
MAX_FOLDERS = 20


def norm_path(path: str) -> str:
    return "/".join(p.strip() for p in (path or "").split("/") if p.strip())


def collection_paths(collections: list[dict]) -> dict[str, str]:
    """Pfad („Rollen/neu“) → Schlüssel für alle Sammlungen einer Bibliothek."""
    by_key = {c["key"]: c for c in collections}

    def path(c, depth=0):
        parent = by_key.get(c.get("parent") or "")
        return f"{path(parent, depth + 1)}/{c['name']}" if parent and depth < 20 else c["name"]

    return {norm_path(path(c)): c["key"] for c in collections}


def ensure_path(port: ZoteroPort, lib: str, path: str, known: dict[str, str]) -> str:
    """Sammlungen entlang des Pfads anlegen, wo sie fehlen. known wird ergänzt."""
    parent, so_far = None, []
    for name in norm_path(path).split("/"):
        so_far.append(name)
        p = "/".join(so_far)
        if p not in known:
            known[p] = port.create_collection(lib, name, parent)
        parent = known[p]
    return parent


def plan(store: Store, pid: int, port: ZoteroPort, lib: str | None = None) -> dict:
    project = store.project(pid)
    lib = lib or project["target_library"]
    folders = {int(f["slot"]): f for f in project["folder_map"] or [] if f.get("path")}
    paths = collection_paths(port.collections(lib))
    done = {(l["record_id"], l["collection"]) for l in store.links(pid) if l["library"] == lib}
    out = {"library": lib, "library_name": project.get("target_name") or lib, "backend": port.backend,
           "folders": [], "unassigned": [], "totals": {"new": 0, "link": 0, "done": 0}, "create_collections": []}
    by_slot: dict[int, dict] = {}
    for slot, f in sorted(folders.items()):
        key = paths.get(norm_path(f["path"]))
        entry = {"slot": slot, "label": f.get("label") or f["path"], "path": norm_path(f["path"]),
                 "collection_key": key, "new": [], "link": [], "done": []}
        if not key:
            out["create_collections"].append(entry["path"])
        by_slot[slot] = entry
        out["folders"].append(entry)
    for rec in store.records(pid):
        d = rec.get("decision")
        if not d or d["status"] != "include":
            continue
        item = {"id": rec["id"], "ref": short_ref({**(rec.get("data") or {}), "year": rec.get("year")}),
                "title": rec["title"], "doi": rec["doi"], "sources": sources_of(rec)}
        entry = by_slot.get(int(d["folder"])) if d.get("folder") is not None else None
        if not entry:
            out["unassigned"].append(item)
            continue
        if entry["collection_key"] and (rec["id"], entry["collection_key"]) in done:
            entry["done"].append(item)
        elif rec.get("zotero_key") and rec.get("zotero_lib") == lib:
            entry["link"].append({**item, "zotero_key": rec["zotero_key"]})
        else:
            entry["new"].append(item)
    for f in out["folders"]:
        for k in ("new", "link", "done"):
            out["totals"][k] += len(f[k])
    return out


def execute(store: Store, pid: int, port: ZoteroPort, *, confirm: bool, lib: str | None = None,
            crossref: Crossref | None = None, progress: Callable[[str], None] | None = None) -> dict:
    if not confirm:
        raise ZoteroWriteRefused("Nach Zotero wird nur nach ausdrücklicher Bestätigung geschrieben.")
    if not port.can_write(lib or store.project(pid)["target_library"]):
        raise ZoteroWriteRefused("Kein Schreibzugriff auf die Zielbibliothek (Schlüssel oder Freigabe fehlt).",
                                 "zotero_auth")
    p = plan(store, pid, port, lib)
    lib = p["library"]
    known = collection_paths(port.collections(lib))
    result = {"created": 0, "linked": 0, "failed": [], "collections_created": [], "enriched": 0}
    for f in p["folders"]:
        if not f["new"] and not f["link"]:
            continue
        before = set(known)
        key = f["collection_key"] or ensure_path(port, lib, f["path"], known)
        result["collections_created"] += sorted(set(known) - before)
        if f["new"]:
            items, rids = [], []
            for it in f["new"]:
                rec = store.record(pid, it["id"])
                data = rec["data"]
                if crossref and data.get("doi"):
                    try:
                        enriched = enrich(data, crossref.work(data["doi"]))
                    except ResearchError:
                        enriched = data
                    if enriched != data:
                        store.update_record_data(rec["id"], enriched)
                        result["enriched"] += 1
                        data = enriched
                catalog = "; ".join(source_label(s) for s in it["sources"]) or "litsearch"
                items.append(to_zotero(data, [key], catalog))
                rids.append(rec["id"])
            if progress:
                progress(f"{f['label']}: {len(items)} neue Einträge")
            for rid, res in zip(rids, port.create_items(lib, items)):
                if res.get("key"):
                    store.add_link(pid, rid, lib, res["key"], key, "created")
                    result["created"] += 1
                else:
                    result["failed"].append({"id": rid, "error": res.get("error", "")})
        if f["link"]:
            keys = [it["zotero_key"] for it in f["link"]]
            port.add_to_collection(lib, key, keys)
            for it in f["link"]:
                store.add_link(pid, it["id"], lib, it["zotero_key"], key, "added")
                result["linked"] += 1
    store.log(pid, "zotero_export", library=lib, backend=port.backend, **{k: v for k, v in result.items() if k != "failed"},
              failed=len(result["failed"]))
    return result

