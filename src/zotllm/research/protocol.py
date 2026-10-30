"""Protokoll als Markdown und CSV (im Stil von PRISMA-S): Quellen, Suchstrings, Daten, Treffer, Duplikate,
Vorfilter, Ein- und Ausschlüsse je Grund, Übergabe an Zotero und die ausgewählte Literatur."""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections import Counter

from .pool import prefilter_label
from .records import short_ref
from .sources import source_label
from .store import Store

STATUS = {"include": "eingeschlossen", "exclude": "ausgeschlossen", "maybe": "unsicher", "open": "offen"}
AI_TEXT = {"include": "passend", "exclude": "nicht passend", "borderline": "Grenzfall", "": ""}


def _limits(limits: dict) -> str:
    if not limits:
        return ""
    parts = []
    if limits.get("year_from") or limits.get("year_to"):
        parts.append(f"{limits.get('year_from') or '…'}–{limits.get('year_to') or '…'}")
    if limits.get("types"):
        parts.append("Typen: " + ", ".join(limits["types"]))
    if limits.get("languages"):
        parts.append("Sprachen: " + ", ".join(limits["languages"]))
    if limits.get("max"):
        parts.append(f"max. {limits['max']}")
    return "; ".join(parts)


def _cell(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def folder_label(project: dict, slot) -> str:
    for f in project.get("folder_map") or []:
        if str(f.get("slot")) == str(slot):
            return f.get("label") or f.get("path") or f"Ordner {slot}"
    return f"Ordner {slot}" if slot is not None else "ohne Ordner"


def markdown(svc, pid: int) -> str:
    """svc: ResearchService (für Vorfilter mit Prüfungen und Recall-Check)."""
    store: Store = svc.store
    p = store.project(pid)
    runs = store.runs(pid)
    items, prefilters = svc._pool_items(pid, p)
    visible = [it for it in items if not it["hidden_by"]]
    links = store.links(pid)
    today = dt.date.today().isoformat()
    ai_items = [it for it in items if it.get("ai")]
    ai_models = sorted({it["ai"].get("model") or "?" for it in ai_items})
    ai_line = (f"KI-gestützte Vorauswahl: {len(ai_items)} Vorschläge von {', '.join(ai_models)} (nur Titel und Abstract); "
               "Entscheidung durch Forschende." if ai_items else "KI-gestützte Vorauswahl: keine; alle Entscheide durch Forschende.")
    L = [f"# Suchprotokoll: {p['title']}", "",
         f"Stand: {today}. Erstellt mit der Recherche-App (litsearch). {ai_line}", ""]
    if p["question"]:
        L += ["## Fragestellung", "", p["question"].strip(), ""]
    if p["description"]:
        L += ["## Kurzbeschreibung", "", p["description"].strip(), ""]
    if p["criteria_in"] or p["criteria_out"]:
        L += ["## Kriterien", ""]
        if p["criteria_in"]:
            L += ["**Einschluss**", "", *[f"- {x.strip()}" for x in p["criteria_in"].splitlines() if x.strip()], ""]
        if p["criteria_out"]:
            L += ["**Ausschluss**", "", *[f"- {x.strip()}" for x in p["criteria_out"].splitlines() if x.strip()], ""]

    L += ["## Suchen", "", "| Datum | Quelle | Suchstring | Limits | Treffer | abgerufen | neu im Pool | Duplikate |",
          "|---|---|---|---|---:|---:|---:|---:|"]
    for r in runs:
        name = f"`{r['name']}`" + (f" (v{r['version']})" if r.get("version") else "")
        if r["kind"] == "import":
            name += f" – Import {r['filename']}"
        L.append(f"| {r['run_at'][:16].replace('T', ' ')} | {source_label(r['source'])} | {name} | {_cell(_limits(r['limits']))} "
                 f"| {r['hits'] if r['hits'] is not None else ''} | {r['fetched']} | {r['new_records']} | {r['duplicates']} |")
    fetched = sum(r["fetched"] for r in runs)
    by_source = Counter(s for it in items for s in it["sources"])
    L += ["", f"Datensätze abgerufen: {fetched}; eindeutige Datensätze im Pool: {len(items)} "
              f"({', '.join(f'{source_label(s)} {n}' for s, n in sorted(by_source.items()))}); "
              f"Duplikate entfernt: {fetched - len(items)} (Abgleich über DOI, PMID, OpenAlex-ID, Accession Number und Titel).", ""]

    shown = set()
    L += ["### Suchstrings", ""]
    for r in runs:
        key = (r["source"], r["name"], r.get("version"), r["string"])
        if key in shown or not r["string"]:
            continue
        shown.add(key)
        L += [f"**{source_label(r['source'])} – {r['name']}" + (f" (v{r['version']})" if r.get("version") else "") + "**",
              "", "```text", r["string"], "```", ""]
        if r.get("translation"):
            L += [f"PubMed-Übersetzung: `{r['translation']}`", ""]

    active = [f for f in prefilters if f.get("active")]
    if active:
        stats = svc.rule_stats(prefilters, items)
        L += ["## Vorfilter vor dem Screening", "",
              "Vorfilter markieren nur; kein Treffer wird durch eine Regel entfernt. Treffer mit einem Ausnahmebegriff "
              "werden nicht ausgeblendet, sondern als Grenzfall gekennzeichnet.", "",
              "| Regel | getroffen | davon Grenzfall (Ausnahme) | ausgeblendet | geprüft | als Grenzfall gekennzeichnet "
              "| aufgenommen | ausgeschlossen |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for f in active:
            st = stats[f["id"]]
            label = _cell(prefilter_label(f))
            if (f.get("exceptions") or "").strip():
                label += f" – Ausnahmen: {_cell(f['exceptions'][:200])}"
            L.append(f"| {label} | {st['matched']} | {st['exception']} | {st['hidden']} | {st['reviewed']} "
                     f"| {st['flagged']} | {st['included']} | {st['excluded']} |")
        unreviewed = sum(1 for it in items if it["hidden_by"] and not it["decision"] and not it["reviews"])
        L += ["", f"Nach Vorfilter zu sichten: {len(visible)}. "
                  + (f"Ausgeblendet und nicht einzeln geprüft: {unreviewed}." if unreviewed
                     else "Alle ausgeblendeten Treffer wurden geprüft."), ""]

    decided = [it for it in visible if it["decision"]]
    status = Counter(it["decision"]["status"] for it in decided)
    borderline = [it for it in items if it["borderline"]]
    no_abs = [it for it in visible if it["no_abstract"]]
    L += ["## Screening (Titel und Abstract)", "",
          f"Gesichtet: {len(decided)} von {len(visible)}; eingeschlossen: {status['include']}; "
          f"unsicher: {status['maybe']}; ausgeschlossen: {status['exclude']}. "
          f"Grenzfälle: {len(borderline)} (davon aufgenommen: "
          f"{sum(1 for it in borderline if it['decision'] and it['decision']['status'] == 'include')}). "
          f"Ohne Abstract (nur Titel gesichtet): {len(no_abs)}.", ""]
    ways = Counter(it["decision"].get("method") or "card" for it in decided if it["decision"]["status"] != "open")
    if ways.get("list"):
        L += [f"Entscheidweise: {ways['card']} einzeln auf Karten, {ways['list']} per Sammel-Übernahme aus der Liste "
              "(Titel, Abstract auf Klick).", ""]
    inc_folders = Counter(folder_label(p, it["decision"].get("folder")) for it in decided if it["decision"]["status"] == "include")
    if inc_folders:
        L += ["| Zielordner | eingeschlossen |", "|---|---:|", *[f"| {_cell(k)} | {v} |" for k, v in inc_folders.items()], ""]
    reasons = Counter((it["decision"].get("reason") or "ohne Angabe") for it in decided if it["decision"]["status"] == "exclude")
    if reasons:
        L += ["| Ausschlussgrund | Anzahl |", "|---|---:|", *[f"| {_cell(k)} | {v} |" for k, v in reasons.most_common()], ""]

    if links:
        L += ["## Übergabe an Zotero", "", f"Bibliothek: {p.get('target_name') or p['target_library']}; "
              f"neu angelegt: {sum(1 for x in links if x['action'] == 'created')}; "
              f"bestehende Einträge zugeordnet: {sum(1 for x in links if x['action'] == 'added')}. "
              "Schlagwort `litsearch`; Angaben über Crossref vervollständigt.", ""]

    if ai_items:
        decided_ai = [it for it in ai_items if it["decision"] and it["decision"]["status"] != "open"]
        pairs = Counter((it["ai"]["label"], it["decision"]["status"]) for it in decided_ai)
        agree = pairs[("include", "include")] + pairs[("exclude", "exclude")]
        comparable = sum(v for (a, h), v in pairs.items() if a in ("include", "exclude") and h in ("include", "exclude"))
        by_label = Counter(it["ai"]["label"] for it in ai_items)
        L += ["## KI-Vorschläge und Entscheide", "",
              f"Vorschläge: passend {by_label['include']}, nicht passend {by_label['exclude']}, Grenzfall {by_label['borderline']}. "
              f"Davon von Forschenden entschieden: {len(decided_ai)}."
              + (f" Übereinstimmung bei „passend“/„nicht passend“: {agree} von {comparable}." if comparable else ""), "",
              "| KI-Vorschlag | aufgenommen | unsicher | ausgeschlossen |", "|---|---:|---:|---:|",
              *[f"| {AI_TEXT[a]} | {pairs[(a, 'include')]} | {pairs[(a, 'maybe')]} | {pairs[(a, 'exclude')]} |"
                for a in ("include", "borderline", "exclude")], ""]
        shown = Counter(it["decision"].get("ai_shown") for it in decided_ai)
        if shown.get(1) or shown.get(0):
            pre = sum(1 for it in decided_ai if it["decision"].get("ai_shown") == 1 and it["decision"].get("method") == "list")
            L += [f"KI-Vorschlag beim Entscheid sichtbar: {shown.get(1, 0)}; ausgeblendet (blind entschieden): "
                  f"{shown.get(0, 0)}" + (f"; ohne Angabe (vor Version 0.4): {shown[None]}" if shown.get(None) else "")
                  + (f". Davon per Sammel-Übernahme mit KI-Vorauswahl: {pre}." if pre else "."), ""]

    spent = [x for x in svc.store.logs(pid) if x["kind"].startswith("ai_") and isinstance((x.get("detail") or {}).get("used"), dict)]
    if spent:
        tasks = {"ai_screening": "Screening-Vorschläge", "ai_sources": "Datenbank-Vorschlag", "ai_blocks": "Konzeptblöcke",
                 "ai_folders": "Unterordner"}
        agg: dict[str, Counter] = {}
        for x in spent:
            u = x["detail"]["used"]
            agg.setdefault(x["kind"], Counter()).update({"n": 1, "in": u.get("input", 0), "out": u.get("output", 0)})
        models = sorted({x["detail"].get("model") or "" for x in spent} - {""})
        L += ["## KI-Nutzung", "", f"Modell: {', '.join(models) or '–'}. Token laut Anbieter (Input einschliesslich "
              "zwischengespeicherter Token).", "", "| Aufgabe | Anfragen | Token Input | Token Output |", "|---|---:|---:|---:|",
              *[f"| {tasks.get(k, k)} | {v['n']} | {v['in']} | {v['out']} |" for k, v in agg.items()],
              f"| **Summe** | {sum(v['n'] for v in agg.values())} | {sum(v['in'] for v in agg.values())} | "
              f"{sum(v['out'] for v in agg.values())} |", ""]

    recall = svc.recall(pid)["papers"]
    if recall:
        L += ["## Recall-Check (Schlüsselarbeiten)", "", "| DOI | Stand |", "|---|---|",
              *[f"| {r['doi']} | {'⚠ ' if r['warn'] else ''}{_cell(r['message'])} |" for r in recall], ""]

    included = [it for it in visible + [x for x in items if x["hidden_by"]] if it["decision"] and it["decision"]["status"] == "include"]
    if included:
        L += ["## Ausgewählte Literatur", ""]
        by_folder: dict[str, list] = {}
        for it in included:
            by_folder.setdefault(folder_label(p, it["decision"].get("folder")), []).append(it)
        for label, rows in by_folder.items():
            L += [f"### {label} ({len(rows)})", "", "| Erstautor/in (Jahr) | Titel | Zeitschrift | DOI | Quelle |",
                  "|---|---|---|---|---|"]
            for it in rows:
                doi = f"[{it['doi']}](https://doi.org/{it['doi']})" if it["doi"] else ""
                title = _cell(it["title"]) + (" *(Grenzfall)*" if it["borderline"] else "")
                L.append(f"| {_cell(short_ref(it))} | {title} | {_cell(it['journal'])} | {doi} "
                         f"| {', '.join(source_label(s) for s in it['sources'])} |")
            L.append("")
    return "\n".join(L).rstrip() + "\n"


def _csv(rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerows(rows)
    return "\ufeff" + buf.getvalue()  # BOM: Excel erkennt UTF-8


def runs_csv(store: Store, pid: int) -> str:
    rows = [["Datum", "Quelle", "Name", "Version", "Art", "Suchstring", "PubMed-Übersetzung", "Limits",
             "Treffer in Datenbank", "Datensätze abgerufen", "neu im Pool", "Duplikate", "Datei"]]
    for r in store.runs(pid):
        rows.append([r["run_at"].replace("T", " ")[:16], source_label(r["source"]), r["name"], r.get("version") or "",
                     "Import" if r["kind"] == "import" else "Suche", r["string"], r.get("translation", ""),
                     _limits(r["limits"]), r["hits"] if r["hits"] is not None else "", r["fetched"], r["new_records"],
                     r["duplicates"], r.get("filename", "")])
    return _csv(rows)


def records_csv(svc, pid: int) -> str:
    p = svc.store.project(pid)
    items, prefilters = svc._pool_items(pid, p)
    labels = {f["id"]: f["label"] for f in prefilters}
    rows = [["ID", "Status", "Zielordner", "Grund", "Erstautor/in (Jahr)", "Titel", "Zeitschrift", "Jahr", "DOI", "PMID",
             "OpenAlex", "Quellen", "Suchstrings", "Vorfilter", "Grenzfall", "Abstract", "KI-Vorschlag", "KI-Begründung",
             "KI sichtbar", "Entscheidweise", "in Zotero"]]
    for it in items:
        d = it["decision"] or {}
        rows.append([it["id"], STATUS.get(d.get("status", "open"), d.get("status")),
                     folder_label(p, d.get("folder")) if d.get("status") == "include" else "", d.get("reason", ""),
                     short_ref(it), it["title"], it["journal"], it["year"] or "", it["doi"], it["pmid"], it["openalex_id"],
                     ", ".join(source_label(s) for s in it["sources"]), ", ".join(it["queries"]),
                     ", ".join(labels.get(h, h) for h in it["hidden_by"]),
                     "; ".join(b.get("reason") or f"{b['label']}: {b['term']} ({'Titel' if b['where'] == 'title' else 'Abstract'})"
                               for b in it["borderline"]),
                     "fehlt" if it["no_abstract"] else (it["abstract_source"] or "ja"),
                     AI_TEXT.get((it.get("ai") or {}).get("label", ""), ""), (it.get("ai") or {}).get("reason", ""),
                     {1: "ja", 0: "nein"}.get(d.get("ai_shown"), ""),
                     {"card": "Karte", "list": "Liste"}.get(d.get("method"), "") if d.get("status", "open") != "open" else "",
                     it["zotero_key"]])
    return _csv(rows)
