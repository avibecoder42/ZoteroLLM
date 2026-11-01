"""Belege auf Einträge, die in Zotero gelöscht wurden (Forschungsstände und gespeicherte Antworten).

Wird ein Eintrag in Zotero gelöscht, entfernt ihn der Abgleich aus dem Katalog; seine Kurzangaben (Titel, Personen,
Jahr, DOI) behält Zotivity in der Tabelle removed_items (Store.delete_items). repair() stellt Belege darauf um:
- Gibt es vom selben Werk noch eine Kopie (gleiche DOI oder gleicher Titel, Erstautor/in und Jahr – wie bei den
  Dubletten), zeigen die Belege auf diese: im Text des Forschungsstands ([@ALT] → [@NEU]; stehen danach beide
  nebeneinander, bleibt einer), in seiner Auswahl und Gliederung sowie in den Quellen gespeicherter Antworten.
- Sonst bleibt der Beleg lesbar (Kurzangaben aus removed_items) und die Prüfung des Forschungsstands meldet ihn.
Fehlen die Kurzangaben (Eintrag vor dieser Version entfernt), holt repair() sie bei laufendem Zotero aus dessen
Papierkorb – die lokale Schnittstelle liefert gelöschte Einträge weiterhin.
"""

from __future__ import annotations

import json
import logging

from zotivity.index.duplicates import normalize_doi, work_keys

log = logging.getLogger(__name__)

Key = tuple[str, str]


def cited_keys(store) -> set[Key]:
    """Alle Einträge, auf die Forschungsstände (Auswahl) und gespeicherte Antworten (Quellen) verweisen."""
    keys = {(r["lib"], r["item_key"]) for r in store.con.execute("SELECT lib, item_key FROM review_docs")}
    for r in store.con.execute("SELECT sources FROM chat_messages WHERE sources IS NOT NULL AND sources != '[]'"):
        try:
            for s in json.loads(r["sources"] or "[]"):
                if s.get("lib") and s.get("item_key"):
                    keys.add((s["lib"], s["item_key"]))
        except ValueError:
            continue
    return keys


def missing(store, keys: set[Key] | None = None) -> set[Key]:
    keys = cited_keys(store) if keys is None else keys
    if not keys:
        return set()
    present = store.items(keys)
    return {k for k in keys if k not in present}


def fetch_from_zotero(engine, keys: set[Key]) -> int:
    """Kurzangaben gelöschter Einträge aus Zotero holen (Papierkorb). Nur bei laufendem Zotero."""
    if not keys:
        return 0
    zot = engine.zotero()
    if not zot.is_available():
        return 0
    n = 0
    for lib, key in sorted(keys):
        try:
            r = zot._request("GET", f"/api/{lib}/items/{key}")
        except Exception as e:  # noqa: BLE001 - Zotero zwischendurch weg: beim nächsten Mal
            log.info("Gelöschter Eintrag %s/%s nicht abrufbar: %s", lib, key, e)
            break
        if r.status_code == 200:
            item = r.json()
            if (item.get("data") or {}).get("itemType") not in ("attachment", "note", "annotation"):
                engine.store.put_removed_item(lib, item)
                n += 1
    return n


def replacements(engine, gone: set[Key]) -> dict[Key, Key]:
    """Gelöschter Eintrag → noch vorhandene Kopie desselben Werks (bei Dubletten die gewählte Kopie)."""
    store = engine.store
    removed = store.removed_items(gone)
    if not removed:
        return {}
    index: dict[str, list[dict]] = {}
    for row in store.work_rows():
        for wk in work_keys(row):
            index.setdefault(wk, []).append(row)
    chosen = engine.copy_resolution()
    out: dict[Key, Key] = {}
    for key, it in removed.items():
        row = {"item_type": it.get("item_type"), "title": it.get("title"), "creators": it.get("creators") or [],
               "year": it.get("year"), "doi": it.get("doi"), "extra": (it.get("data") or {}).get("extra") or ""}
        doi = normalize_doi(row["doi"]) or normalize_doi(row["extra"])
        found: list[dict] = []
        for wk in work_keys(row):
            for cand in index.get(wk, []):
                cdoi = normalize_doi(cand.get("doi")) or normalize_doi(cand.get("extra"))
                if wk.startswith("t:") and doi and cdoi and doi != cdoi:
                    continue  # verschiedene DOIs: verschiedene Fassungen, nicht dasselbe Werk
                found.append(cand)
        if found:
            best = sorted(found, key=lambda c: (c["lib"] != key[0], c["lib"], c["key"]))[0]
            target = (best["lib"], best["key"])
            out[key] = chosen.get(target, target)
    return out


def _rewrite_citations(text: str, mapping: dict[str, str]) -> str:
    """[@ALT, S. 3; @NEU] → [@NEU, S. 3]: Schlüssel ersetzen, doppelte zusammenfassen (mit Seite vor ohne)."""
    from zotivity.rag.review import ReviewService, format_citation, parse_citation

    def repl(m):
        parts = parse_citation(m.group(1))
        if not any(k in mapping for k, _ in parts):
            return m.group(0)
        out: list[tuple[str, str]] = []
        for k, p in parts:
            k = mapping.get(k, k)
            if (k, p) not in out:
                out.append((k, p))
        with_page = {k for k, p in out if p}
        return format_citation([(k, p) for k, p in out if p or k not in with_page])

    return ReviewService._CITE.sub(repl, text)


def apply(engine, mapping: dict[Key, Key]) -> dict:
    """Belege umstellen: Forschungsstände (Text, Auswahl, Gliederung) und Quellen gespeicherter Antworten."""
    from zotivity.zotero import zotero_select_url

    store = engine.store
    by_key = {old[1]: new[1] for old, new in mapping.items()}
    reviews = set()
    for old, new in mapping.items():
        rows = store.con.execute("SELECT DISTINCT review_id FROM review_docs WHERE lib=? AND item_key=?", old).fetchall()
        for r in rows:
            reviews.add(r["review_id"])
            store.replace_review_doc(r["review_id"], old, new)
    for rid in reviews:
        review = store.get_review(rid)
        if not review:
            continue
        state = review["state"]
        for sec in state.get("sections") or []:
            sec["text"] = _rewrite_citations(sec.get("text") or "", by_key)
        for sec in (state.get("outline") or {}).get("sections") or []:
            if sec.get("keys"):
                sec["keys"] = list(dict.fromkeys(by_key.get(k, k) for k in sec["keys"]))
        store.update_review_state(rid, state)
        if state.get("check"):
            try:
                from zotivity.rag.review import ReviewService

                ReviewService(engine).check(rid)
            except Exception as e:  # noqa: BLE001 - die Prüfung lässt sich jederzeit neu starten
                log.warning("Prüfung nach dem Umstellen nicht aufgefrischt: %s", e)
    messages = 0
    for old, new in mapping.items():
        pdf = next((a["key"] for a in store.attachments_for_item(*new)
                    if a["status"] == "indexed" and a["content_type"] == "application/pdf"), "")
        for r in store.con.execute("SELECT id, sources FROM chat_messages WHERE sources LIKE ?", (f"%{old[1]}%",)).fetchall():
            sources = json.loads(r["sources"] or "[]")
            changed = False
            for s in sources:
                if (s.get("lib"), s.get("item_key")) == old:
                    s.update(lib=new[0], item_key=new[1], att_key=pdf or s.get("att_key", ""),
                             zotero_select=zotero_select_url(*new))
                    changed = True
            if changed:
                with store.write() as con:
                    con.execute("UPDATE chat_messages SET sources=? WHERE id=?",
                                (json.dumps(sources, ensure_ascii=False), r["id"]))
                messages += 1
    return {"reviews": len(reviews), "messages": messages}


def repair(engine, fetch: bool = True) -> dict:
    """Belege auf gelöschte Einträge umstellen, wo es eine Kopie gibt. Rückgabe: umgestellt, ohne Ersatz."""
    store = engine.store
    gone = missing(store)
    if not gone:
        return {"replaced": 0, "unresolved": []}
    if fetch:
        known = store.removed_items(gone)
        fetch_from_zotero(engine, {k for k in gone if k not in known})
    mapping = replacements(engine, gone)
    done = apply(engine, mapping) if mapping else {"reviews": 0, "messages": 0}
    if mapping:
        log.info("Belege auf in Zotero gelöschte Einträge umgestellt: %s (%s)",
                 ", ".join(f"{a[1]}→{b[1]}" for a, b in mapping.items()), done)
    return {"replaced": len(mapping), **done, "unresolved": sorted(gone - set(mapping))}
