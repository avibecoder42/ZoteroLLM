"""Dubletten: dasselbe Werk als mehrere Zotero-Einträge (z. B. in „Meine Bibliothek“ und in einer Gruppe).

Erkennung aus den Metadaten im Index (Suchkatalog bzw. Abgleich):
- gleiche DOI (Feld DOI oder Zeile „DOI: …“ im Feld Extra);
- ohne DOI: gleicher Titel, gleiche Erstautorin bzw. gleicher Erstautor und gleiches Jahr. Kurze Titel wie
  „Editorial“ oder „Einleitung“ (weniger als MIN_TITLE_WORDS Wörter) werden nur über die DOI zusammengefasst;
  Einträge mit verschiedenen DOIs nie (meist verschiedene Fassungen, z. B. Preprint und Artikel).

Je Werk wird genau eine Kopie verwendet: die von Hand gewählte, sonst die nach der Regel – lesbarer Volltext vor
fehlendem, erkannte Seitenzahlen, bevorzugte Bibliothek. Die übrigen Kopien werden weder gelesen noch eingebettet;
Fragen und Forschungsstand sehen das Werk einmal, über die gewählte Kopie – auch in Korpora, die nur eine andere
Kopie enthalten (der Umfang wird auf die gewählte Kopie abgebildet, siehe Engine.resolve_copies).

Entscheidungen (Tabelle duplicate_choices, je Werk):
- user: von Hand gewählte Kopie (bleibt fest, solange sie zum Werk gehört);
- rule: zur Kenntnis genommen, Kopie nach der Regel (folgt dem Zustand, z. B. wenn die gewählte keinen Text hat);
- separate: keine Dublette – alle Kopien werden einzeln verwendet.
Werke ohne Eintrag sind „neu“: Vor einem Lauf von Hand fragt die Oberfläche nach; ein Lauf ohne Rückfrage
(Hintergrund, Zotero-Plugin) übernimmt die Regel und vermerkt das Werk als „rule“.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable

Key = tuple[str, str]

MIN_TITLE_WORDS = 3
SKIP_TYPES = ("attachment", "note", "annotation")
_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)


def normalize_doi(value: str | None) -> str:
    m = _DOI.search(value or "")
    return m.group(0).rstrip(".,;)]").lower() if m else ""


def normalize_text(value: str | None) -> str:
    s = unicodedata.normalize("NFKD", (value or "").replace("ß", "ss"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^0-9a-z]+", " ", s).strip()


def title_key(title: str | None, creators: list[dict], year: int | None) -> str:
    """„titel|erstautor|jahr“ – leer, wenn eines fehlt oder der Titel zu kurz ist."""
    t = normalize_text(title)
    if len(t.split()) < MIN_TITLE_WORDS or not year:
        return ""
    first = next((c for c in creators or [] if c.get("lastName") or c.get("name")), None)
    author = normalize_text((first or {}).get("lastName") or (first or {}).get("name"))
    return f"{t}|{author}|{year}" if author else ""


def work_keys(row: dict) -> list[str]:
    """Kennungen eines Werks: „doi:…“ und/oder „t:titel|autor|jahr“ (leer für Anhänge und Notizen)."""
    if row.get("item_type") in SKIP_TYPES:
        return []
    doi = normalize_doi(row.get("doi")) or normalize_doi(row.get("extra"))
    tk = title_key(row.get("title"), row.get("creators") or [], row.get("year"))
    return [k for k in (f"doi:{doi}" if doi else "", f"t:{tk}" if tk else "") if k]


def find_groups(rows: Iterable[dict]) -> dict[str, list[Key]]:
    """Werke mit mehreren Einträgen: {werk: [(lib, key), …]}. rows: lib, key, item_type, title, creators (Liste),
    year, doi, extra. Werk-Kennung: „doi:…“ oder „t:titel|autor|jahr“."""
    by_doi: dict[str, set[Key]] = {}
    doi_of_title: dict[str, set[str]] = {}
    without_doi: list[tuple[Key, str]] = []
    for r in rows:
        if r.get("item_type") in SKIP_TYPES:
            continue
        key = (r["lib"], r["key"])
        doi = normalize_doi(r.get("doi")) or normalize_doi(r.get("extra"))
        tk = title_key(r.get("title"), r.get("creators") or [], r.get("year"))
        if doi:
            by_doi.setdefault(doi, set()).add(key)
            if tk:
                doi_of_title.setdefault(tk, set()).add(doi)
        elif tk:
            without_doi.append((key, tk))
    groups: dict[str, set[Key]] = {f"doi:{d}": keys for d, keys in by_doi.items()}
    by_title: dict[str, set[Key]] = {}
    for key, tk in without_doi:
        dois = doi_of_title.get(tk, set())
        if len(dois) == 1:  # Kopie ohne DOI eines Werks mit DOI
            groups[f"doi:{next(iter(dois))}"].add(key)
        else:
            by_title.setdefault(tk, set()).add(key)
    groups.update({f"t:{tk}": keys for tk, keys in by_title.items()})
    return {w: sorted(keys) for w, keys in groups.items() if len(keys) > 1}


def quality(store, keys: Iterable[Key]) -> dict[Key, tuple[int, int]]:
    """Je Kopie (Text, Seitenzahlen): Text 2 = gelesen, 1 = lesbare Datei noch nicht gelesen, 0 = keine;
    Seitenzahlen 1 = gedruckte Seitenzahlen erkannt."""
    out = {k: (0, 0) for k in keys}
    for (lib, parent), atts in store.attachments_of(out).items():
        text = pages = 0
        for a in atts:
            if a["status"] == "indexed" and (a["n_chunks"] or 0) > 0:
                text = 2
                try:
                    pages = pages or int(any(json.loads(a["page_labels"] or "[]")))
                except ValueError:
                    pass
            elif a["status"] == "pending":
                text = max(text, 1)
        out[(lib, parent)] = (text, pages)
    return out


def rule_choice(copies: list[Key], q: dict[Key, tuple[int, int]], prefer_lib: str) -> Key:
    """Regel: lesbarer Volltext, dann Seitenzahlen, dann bevorzugte Bibliothek, dann „Meine Bibliothek“."""
    return sorted(copies, key=lambda k: (-q.get(k, (0, 0))[0], -q.get(k, (0, 0))[1], k[0] != prefer_lib,
                                         k[0] != "users/0", k))[0]


def resolve(store, prefer_lib: str) -> dict[str, dict]:
    """Je Werk: Kopien, gewählte Kopie, Regelwahl, Entscheidung (mode: user, rule, separate oder None)."""
    groups = store.duplicate_groups()
    if not groups:
        return {}
    choices = store.duplicate_choices()
    q = quality(store, (k for keys in groups.values() for k in keys))
    out = {}
    for work, copies in groups.items():
        c = choices.get(work) or {}
        mode = c.get("mode")
        rule = rule_choice(copies, q, prefer_lib)
        chosen = rule
        if mode == "user" and (c.get("lib"), c.get("item_key")) in copies:
            chosen = (c["lib"], c["item_key"])
        out[work] = {"copies": copies, "chosen": None if mode == "separate" else chosen, "rule": rule,
                     "mode": mode, "quality": {k: q[k] for k in copies}}
    return out


def hidden_copies(store, prefer_lib: str) -> dict[Key, Key]:
    """Nicht gewählte Kopie → gewählte Kopie (Werke mit „keine Dublette“ fehlen)."""
    out: dict[Key, Key] = {}
    for g in resolve(store, prefer_lib).values():
        if g["chosen"]:
            out.update({k: g["chosen"] for k in g["copies"] if k != g["chosen"]})
    return out


def works_touching(store, scope: set[Key]) -> list[str]:
    """Werke, von denen mindestens eine Kopie im (unaufgelösten) Umfang liegt."""
    return [w for w, keys in store.duplicate_groups().items() if any(k in scope for k in keys)]


def collection_paths(store) -> dict[Key, str]:
    """(lib, Sammlung) → „Obersammlung › Sammlung“."""
    by = {(r["lib"], r["key"]): r for r in store.collections()}

    def path(lib: str, key: str, depth: int = 0) -> str:
        r = by.get((lib, key))
        if not r:
            return ""
        parent = path(lib, r["parent"], depth + 1) if r["parent"] and depth < 20 else ""
        return f"{parent} › {r['name']}" if parent else r["name"]

    return {k: path(*k) for k in by}


def describe(store, prefer_lib: str, works: Iterable[str] | None = None) -> list[dict]:
    """Werke mit ihren Kopien für die Oberfläche: Bibliothek, Sammlungen, Text/Seitenzahlen, gewählt, Regelwahl."""
    from zotivity.index.store import strip_bidi

    res = resolve(store, prefer_lib)
    if works is not None:
        res = {w: res[w] for w in works if w in res}
    if not res:
        return []
    items = store.items({k for g in res.values() for k in g["copies"]})
    names = {"users/0": "Meine Bibliothek", **store.library_names()}
    paths = collection_paths(store)
    out = []
    for work, g in res.items():
        copies = []
        for k in g["copies"]:
            it = items.get(k) or {}
            text, pages = g["quality"][k]
            copies.append({
                "lib": k[0], "key": k[1], "library": names.get(k[0], k[0]), "title": it.get("title") or k[1],
                "creators": strip_bidi(it.get("creator_summary") or ""), "year": it.get("year"),
                "item_type": it.get("item_type") or "", "publication": it.get("publication") or "",
                "collections": [p for p in (paths.get((k[0], c), "") for c in it.get("collections") or []) if p],
                "text": text, "pages": bool(pages), "chosen": k == g["chosen"], "rule": k == g["rule"]})
        main = next((c for c in copies if c["chosen"] or c["rule"]), copies[0])
        out.append({"work": work, "doi": work[4:] if work.startswith("doi:") else "", "mode": g["mode"],
                    "title": main["title"], "creators": main["creators"], "year": main["year"], "copies": copies})
    out.sort(key=lambda g: (g["creators"].casefold(), g["year"] or 0, g["title"].casefold()))
    return out


def acknowledge(store, scope: set[Key]) -> int:
    """Lauf ohne Rückfrage: neue Werke im Umfang übernehmen die Regel. Rückgabe: Zahl der neu vermerkten Werke."""
    known = store.duplicate_choices()
    new = [w for w in works_touching(store, scope) if w not in known]
    for w in new:
        store.set_duplicate_choice(w, "rule")
    return len(new)
