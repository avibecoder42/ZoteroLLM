"""Fassade der Recherche: verbindet Ablage, Quellen und Zotero. Die API (api.py) ruft nur diese Klasse auf."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePath

from . import ai as ai_mod
from . import export as export_mod
from . import protocol
from .errors import NotFound, ResearchError, SourceError, ZoteroWriteRefused
from .http import Http
from .pool import DEFAULT_PREFILTERS, exception_hit, filter_pool, matches, status_of, summarize, with_ids
from .ports import KEY_NCBI, KEY_OPENALEX, KEY_SEMANTICSCHOLAR, ChatModel, KeyStore, ZoteroPort
from .querybuild import TRANSLATABLE, build_all, clean_terms, parse_pubmed
from .querybuild import translate as translate_query_string
from .records import dedup_keys, dedup_keys_zotero, find_dois, norm_doi
from .sources import LIVE_SOURCES, SOURCES, SearchResult, source_label
from .sources import catalog
from .sources import ris as ris_mod
from .sources.arxiv import ArXiv
from .sources.crossref import Crossref
from .sources.econbiz import EconBiz
from .sources.eric import ERIC
from .sources.europepmc import EuropePMC
from .sources.openalex import OpenAlex
from .sources.osf import OSFPreprints
from .sources.pubmed import PubMed
from .sources.semanticscholar import SemanticScholar
from .sources.swisscovery import Swisscovery
from .store import Store, now

STATUSES = ("include", "exclude", "maybe", "open")
FOLDER_SLOTS = range(1, export_mod.MAX_FOLDERS + 1)
VERDICTS = ("restore", "borderline", "exclude")
DEFAULT_SOURCES = ["pubmed", "openalex"]
# Voreinstellungen je Quelle beim Übersetzen (wie im Projekt Onlineaggression bei OpenAlex)
DEFAULT_LIMITS = {"openalex": {"types": ["article", "review"], "max": 200}}


@dataclass
class ResearchConfig:
    email: str = ""          # für NCBI, OpenAlex und Crossref („polite pool“)
    zotero_user_id: str = ""
    user_name: str = ""      # wer entscheidet (Protokoll)


class ResearchService:
    def __init__(self, store: Store, keys: KeyStore, zotero: dict[str, ZoteroPort] | None = None,
                 http: Http | None = None, chat: ChatModel | None = None, config: ResearchConfig | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.store = store
        self.keys = keys
        self.zotero = zotero or {}
        self.http = http or Http(sleep=sleep)
        self.chat = chat  # KI-Vorauswahl folgt in Phase 2b
        self.config = config or ResearchConfig()
        self.sleep = sleep

    # ------------------------------------------------------------------------------------------ Quellen
    def pubmed(self) -> PubMed:
        return PubMed(self.http, self.keys.get(KEY_NCBI), self.config.email or None, sleep=self.sleep)

    def openalex(self) -> OpenAlex:
        return OpenAlex(self.http, self.config.email or None, self.keys.get(KEY_OPENALEX))

    def crossref(self) -> Crossref:
        return Crossref(self.http, self.config.email or None)

    def semanticscholar(self) -> SemanticScholar:
        return SemanticScholar(self.http, self.keys.get(KEY_SEMANTICSCHOLAR))

    def source(self, name: str):
        factories = {
            "pubmed": self.pubmed, "openalex": self.openalex, "semanticscholar": self.semanticscholar,
            "europepmc": lambda: EuropePMC(self.http, self.config.email or None),
            "eric": lambda: ERIC(self.http), "econbiz": lambda: EconBiz(self.http),
            "arxiv": lambda: ArXiv(self.http, sleep=self.sleep), "osf": lambda: OSFPreprints(self.http),
            "swisscovery": lambda: Swisscovery(self.http),
        }
        if name not in factories:
            raise ResearchError(f"{source_label(name)} lässt sich nicht direkt durchsuchen – Export als RIS importieren.",
                                "not_live")
        return factories[name]()

    def zotero_port(self, backend: str | None) -> ZoteroPort:
        port = self.zotero.get(backend or "web")
        if not port:
            raise ResearchError(f"Zotero-Zugang „{backend}“ ist nicht eingerichtet.", "zotero_config")
        return port

    def info(self) -> dict:
        keys = {k: bool(self.keys.get(k)) for k in (KEY_NCBI, KEY_OPENALEX, KEY_SEMANTICSCHOLAR)}
        return {
            "sources": [{"id": k, "label": v, "live": k in LIVE_SOURCES} for k, v in SOURCES.items()],
            "catalog": [{**s, "key_ok": keys.get(s["key"]) if s["key"] else None} for s in catalog.CATALOG],
            "disciplines": catalog.DISCIPLINES,
            "access": catalog.ACCESS,
            "translatable": list(TRANSLATABLE),
            "zotero_backends": list(self.zotero),
            "ai": {k: v for k, v in self.ai_status().items() if k not in ("usage", "cost")},
            "keys": keys,
            "email": bool(self.config.email),
            "folder_slots": list(FOLDER_SLOTS),
            "max_folders": export_mod.MAX_FOLDERS,
        }

    @staticmethod
    def suggest_sources(disciplines: list[str]) -> list[str]:
        return catalog.suggest(disciplines)

    # ------------------------------------------------------------------------------------------ Projekte
    def list_projects(self) -> list[dict]:
        return [{**p, "summary": self.summary(p["id"])} for p in self.store.projects()]

    def _settings(self, p: dict) -> dict:
        s = dict(p.get("settings") or {})
        s["sources"] = [x for x in s.get("sources") or [] if x in catalog.BY_ID and catalog.BY_ID[x]["access"] != "never"]
        if not s["sources"]:  # ältere Projekte: die Quellen, die schon Suchstrings haben
            used = {q["source"] for q in self.store.queries(p["id"])} if p.get("id") else set()
            s["sources"] = [x for x in DEFAULT_SOURCES + sorted(used) if x in SOURCES]
            s["sources"] = list(dict.fromkeys(s["sources"]))
        s.setdefault("disciplines", [])
        s.setdefault("key_papers", [])
        s.setdefault("ai_visible", True)  # KI-Schalter im Screening
        return s

    def get_project(self, pid: int) -> dict:
        p = self.store.project(pid)
        p["prefilters"] = with_ids(p["prefilters"])
        p["settings"] = self._settings(p)
        p["blocks"] = self.store.blocks(pid)
        p["summary"] = self.summary(pid)
        return p

    def create_project(self, data: dict) -> dict:
        data = dict(data)
        data.setdefault("prefilters", DEFAULT_PREFILTERS)
        data["prefilters"] = with_ids(data["prefilters"])
        p = self.store.create_project(data)
        self.store.log(p["id"], "project_created", title=p["title"])
        return self.get_project(p["id"])

    def update_project(self, pid: int, data: dict) -> dict:
        data = dict(data)
        if data.get("prefilters") is not None:
            keep = ("count", "label", "matched", "hidden", "borderline", "reviewed")
            data["prefilters"] = [{k: v for k, v in f.items() if k not in keep} for f in with_ids(data["prefilters"])]
        if data.get("folder_map") is not None:
            data["folder_map"] = clean_folder_map(data["folder_map"])
        if data.get("settings") is not None:  # zusammenführen statt ersetzen
            data["settings"] = {**(self.store.project(pid).get("settings") or {}), **data["settings"]}
            if "sources" in data["settings"]:  # „nicht erlaubt“ ist nie wählbar
                data["settings"]["sources"] = [s for s in data["settings"]["sources"]
                                               if s in catalog.BY_ID and catalog.BY_ID[s]["access"] != "never"]
        self.store.update_project(pid, data)
        return self.get_project(pid)

    def delete_project(self, pid: int) -> None:
        self.store.delete_project(pid)

    def _records(self, pid: int) -> list[dict]:
        """Der Pool: Treffer der jeweils letzten Suche je Suchstring und Quelle, dazu RIS-Importe. Treffer, die nur noch
        aus früheren Suchen oder gelöschten Suchstrings stammen, bleiben nur, wenn sie schon entschieden sind."""
        return [r for r in self.store.records(pid) if r["current"] or r["decision"]]

    def _pool_items(self, pid: int, project: dict | None = None) -> tuple[list[dict], list[dict]]:
        p = project or self.store.project(pid)
        prefilters = with_ids(p["prefilters"])
        reviews = self.store.reviews(pid)
        return [summarize(r, prefilters, reviews.get(r["id"])) for r in self._records(pid)], prefilters

    def reset_pool(self, pid: int, confirm: bool = False) -> dict:
        """Pool zurücksetzen: alle Treffer, Entscheide und KI-Vorschläge löschen (nur nach Bestätigung)."""
        if not confirm:
            raise ResearchError("Zurücksetzen nur nach ausdrücklicher Bestätigung.")
        decided = sum(1 for d in self.store.current_decisions(pid).values() if d["status"] != "open")
        n = self.store.delete_records(pid)
        self.store.log(pid, "pool_reset", records=n, decisions=decided)
        return {"deleted": n, "decisions": decided}

    def summary(self, pid: int) -> dict:
        """Kopfzeile jeder Ansicht: „PubMed 503 · OpenAlex 937 · gesichtet 380/1150 · ausgewählt 71“."""
        p = self.store.project(pid)
        items, prefilters = self._pool_items(pid, p)
        visible = [it for it in items if not it["hidden_by"]]
        status = Counter(status_of(it) for it in visible)
        recall = self._recall(p, items)
        return {
            "sources": dict(Counter(s for it in items for s in it["sources"])),
            "pool": len(items),
            "visible": len(visible),
            "hidden": len(items) - len(visible),
            "hidden_unreviewed": sum(1 for it in items if it["hidden_by"] and not it["decision"]),
            "screened": len(visible) - status["open"],
            "included": sum(1 for it in items if status_of(it) == "include"),
            "maybe": status["maybe"],
            "excluded": status["exclude"],
            "borderline": sum(1 for it in visible if it["borderline"]),
            "borderline_open": sum(1 for it in visible if it["borderline"] and status_of(it) == "open"),
            "no_abstract": sum(1 for it in items if it["no_abstract"]),
            "in_zotero": sum(1 for it in items if it["zotero_key"]),
            "by_folder": {str(k): v for k, v in Counter(it["decision"]["folder"] for it in items
                                                          if status_of(it) == "include").items()},
            "queries": len(self.store.queries(pid)),
            "runs": len(self.store.runs(pid)),
            "key_papers": len(recall),
            "recall_warnings": sum(1 for r in recall if r["warn"]),
        }

    # ------------------------------------------------------------------------------------------ Suchstrategie
    def set_blocks(self, pid: int, blocks: list[dict]) -> list[dict]:
        return self.store.replace_blocks(pid, blocks)

    def build(self, pid: int, blocks: list[dict] | None = None) -> dict:
        p = self.store.project(pid)
        sources = self._settings(p)["sources"]
        return build_all(blocks if blocks is not None else self.store.blocks(pid), sources)

    @staticmethod
    def translate(string: str, to: str = "openalex") -> dict:
        if to not in TRANSLATABLE:
            raise ResearchError(f"Übersetzen nach {source_label(to)} ist nicht vorgesehen.")
        return translate_query_string(string, to)

    def translate_query(self, qid: int, targets: list[str]) -> list[dict]:
        """PubMed-Suchstring in die gewählten Quellen übersetzen; je Quelle eine neue Version mit gleichem Namen."""
        q = self.store.query(qid)
        if q["source"] != "pubmed":
            raise ResearchError("Übersetzt wird von PubMed aus – bitte einen PubMed-Suchstring wählen.")
        out = []
        for t in targets:
            if t == "pubmed":
                continue
            r = self.translate(q["string"], t)
            if not r["string"]:
                continue
            existing = [x for x in self.store.queries(q["project_id"]) if x["name"] == q["name"] and x["source"] == t]
            if existing and existing[0]["string"] == r["string"]:
                out.append({**existing[0], "notes": r["notes"]})
                continue
            note = f"übersetzt aus PubMed v{q['version']}" + (f"; {' '.join(r['notes'])}" if r["notes"] else "")
            limits = existing[0]["limits"] if existing else DEFAULT_LIMITS.get(t, {})
            out.append({**self.add_query(q["project_id"], q["name"], t, r["string"], limits, note), "notes": r["notes"]})
        return out

    def terms(self, pid: int) -> dict:
        """Begriffe aus Suchstrategie und Suchstrings – als Vorschläge für Ausnahmen bei Ausschlussregeln."""
        p = self.store.project(pid)
        blocks = [{"name": b["name"] or "Block", "kind": b["kind"], "terms": clean_terms(b["terms"])}
                  for b in self.store.blocks(pid) if clean_terms(b["terms"])]
        queries = []
        for q in self.store.queries(pid):
            if q["source"] != "pubmed":
                continue
            found: list[str] = []

            def walk(n, negated=False):
                if n[0] == "term":
                    t = n[1].strip().strip('"').strip()
                    if t and not negated and t.lower() not in (x.lower() for x in found):
                        found.append(t)
                elif n[0] == "group":
                    walk(n[1], negated)
                else:
                    walk(n[1], negated)
                    walk(n[2], negated or n[0] == "not")

            walk(parse_pubmed(q["string"]))
            queries.append({"name": q["name"], "terms": found})
        return {"blocks": blocks, "queries": queries, "project": p["title"]}

    # ------------------------------------------------------------------------------------------ Suchstrings
    def queries(self, pid: int) -> list[dict]:
        self.store.project(pid)
        runs = self.store.runs(pid)
        out = []
        for q in self.store.queries(pid):
            last = [r for r in runs if r["source"] == q["source"] and r["name"] == q["name"] and r["kind"] == "search"]
            out.append({**q, "last_run": last[-1] if last else None,
                        "current_run": bool(last and last[-1]["version"] == q["version"])})
        return out

    def add_query(self, pid: int, name: str, source: str, string: str, limits: dict | None = None, note: str = "") -> dict:
        name, string = (name or "").strip(), (string or "").strip()
        if not name or not string:
            raise ResearchError("Name und Suchstring dürfen nicht leer sein.")
        if source not in SOURCES:
            raise ResearchError(f"Unbekannte Quelle: {source}")
        q = self.store.add_query(pid, name, source, string, limits, note)
        self.store.log(pid, "query_saved", name=name, source=source, version=q["version"])
        return q

    def import_query_files(self, pid: int, files: list[dict], source: str = "pubmed",
                           limits: dict | None = None) -> list[dict]:
        """Suchstrings aus Textdateien (z. B. queries/cyberaggression/*.txt): Name = Dateiname ohne Endung."""
        out = []
        for f in files:
            text = f.get("content") or ""
            string = " ".join(text.split())
            if not string:
                continue
            name = PurePath(f.get("filename") or "Suchstring").stem
            existing = [q for q in self.store.queries(pid) if q["name"] == name and q["source"] == source]
            if existing and existing[0]["string"] == string:
                out.append(existing[0])
                continue
            out.append(self.add_query(pid, name, source, string, limits, note=f"aus {f.get('filename', '')}"))
        return out

    def update_query(self, qid: int, data: dict) -> dict:
        return self.store.update_query(qid, string=data.get("string"), limits=data.get("limits"),
                                       name=data.get("name"), note=data.get("note"))

    def delete_query(self, qid: int) -> None:
        self.store.delete_query(qid)

    def count(self, source: str, string: str, limits: dict | None = None) -> dict:
        if not (string or "").strip():
            return {"count": 0, "translation": "", "warnings": [], "upper_bound": False}
        res: SearchResult = self.source(source).count(string, limits)
        return {"count": res.count, "translation": res.translation, "warnings": res.warnings, "upper_bound": res.upper_bound}

    def count_query(self, qid: int) -> dict:
        q = self.store.query(qid)
        res = self.count(q["source"], q["string"], q["limits"])
        self.store.set_count(qid, res["count"], res["translation"])
        self.store.log(q["project_id"], "count", name=q["name"], source=q["source"], version=q["version"], hits=res["count"])
        return {**self.store.query(qid), "warnings": res["warnings"], "upper_bound": res["upper_bound"]}

    def run_query(self, qid: int, max_records: int | None = None) -> dict:
        q = self.store.query(qid)
        pid = q["project_id"]
        limits = q["limits"] or {}
        res = self.source(q["source"]).search(q["string"], limits, max_records or limits.get("max"))
        run_id = self.store.add_run(pid, query_id=qid, kind="search", source=q["source"], name=q["name"],
                                    string=q["string"], version=q["version"], limits=limits, hits=res.count,
                                    translation=res.translation, note="; ".join(res.warnings))
        stats = self.store.add_records(pid, run_id, res.records)
        self.store.update_run(run_id, fetched=stats["fetched"], new_records=stats["new"],
                              duplicates=stats["duplicates"] + stats["duplicates_in_run"])
        self.store.set_count(qid, res.count, res.translation)
        self.store.log(pid, "run", run=run_id, name=q["name"], source=q["source"], hits=res.count, **stats)
        return {"run": run_id, "hits": res.count, "warnings": res.warnings, **stats}

    def runs(self, pid: int) -> list[dict]:
        self.store.project(pid)
        return self.store.runs(pid)

    def import_ris(self, pid: int, filename: str, content: str | bytes, source: str = "ris", name: str = "",
                   string: str = "", hits: int | None = None) -> dict:
        self.store.project(pid)
        records = ris_mod.parse(content)
        if not records:
            raise ResearchError("Keine RIS-Datensätze gefunden. Ist die Datei im RIS-Format exportiert?", "ris")
        name = name or PurePath(filename or "Import").stem
        run_id = self.store.add_run(pid, kind="import", source=source or "ris", name=name, string=string or "",
                                    hits=hits, filename=filename or "")
        stats = self.store.add_records(pid, run_id, records)
        self.store.update_run(run_id, fetched=stats["fetched"], new_records=stats["new"],
                              duplicates=stats["duplicates"] + stats["duplicates_in_run"])
        self.store.log(pid, "import", run=run_id, filename=filename, source=source, **stats)
        return {"run": run_id, "hits": hits, **stats}

    # ------------------------------------------------------------------------------------------ Pool
    @staticmethod
    def rule_stats(prefilters: list[dict], items: list[dict]) -> dict[str, dict]:
        """Je Regel: getroffen, ausgeblendet, Grenzfall (Ausnahme), geprüft, aufgenommen, ausgeschlossen."""
        out = {}
        for f in prefilters:
            hit = [it for it in items if f["id"] in it["matched_by"]]
            out[f["id"]] = {
                "matched": len(hit),
                "hidden": sum(1 for it in hit if f["id"] in it["hidden_by"]),
                "exception": sum(1 for it in hit if any(b["rule"] == f["id"] for b in it["borderline"])),
                "reviewed": sum(1 for it in hit if f["id"] in it["reviews"] or it["decision"]),
                "flagged": sum(1 for it in hit if it["borderline"]),
                "included": sum(1 for it in hit if status_of(it) == "include"),
                "excluded": sum(1 for it in hit if status_of(it) == "exclude"),
            }
        return out

    def pool(self, pid: int, **filters) -> dict:
        p = self.store.project(pid)
        items, prefilters = self._pool_items(pid, p)
        stats = self.rule_stats(prefilters, items)
        records = self._records(pid)
        for f in prefilters:  # abgeschaltete Regel: wie viele sie ausblenden würde
            if not f.get("active"):
                stats[f["id"]]["hidden"] = sum(1 for rec in records if matches(f, rec) and not exception_hit(f, rec))
        shown = filter_pool(items, **{k: v for k, v in filters.items() if v not in (None, "")})
        return {"items": shown, "total": len(items), "hidden": sum(1 for it in items if it["hidden_by"]),
                "prefilters": [{**f, **stats.get(f["id"], {}), "count": stats.get(f["id"], {}).get("hidden", 0)}
                               for f in prefilters],
                "queries": sorted({q for it in items for q in it["queries"]}),
                "sources": sorted({s for it in items for s in it["sources"]}),
                "no_abstract": sum(1 for it in items if it["no_abstract"]),
                "stale": sum(1 for it in items if it["stale"]),
                "abstracts_open": sum(1 for r in records if self._needs_abstract(r)),
                "abstracts_retry": sum(1 for r in records if self._needs_abstract(r, True))}

    def zotero_match(self, pid: int, backend: str | None = None) -> dict:
        """Abgleich mit der Zotero-Zielbibliothek: welche Treffer sind schon da (DOI, PMID, Titel)?"""
        p = self.store.project(pid)
        port = self.zotero_port(backend or p["zotero_backend"])
        lib = p["target_library"]
        index: dict[str, str] = {}
        n_items = 0
        for item in port.iter_items(lib):
            n_items += 1
            for k in dedup_keys_zotero(item.get("data") or {}):
                index.setdefault(k, item["key"])
        self.store.replace_zotero_index(pid, lib, index)
        found = {}
        for rec in self._records(pid):
            hit = next((index[k] for k in dedup_keys(rec.get("data") or {}) if k in index), None)
            if hit:
                found[rec["id"]] = hit
        self.store.set_zotero_matches(pid, lib, found)
        self.store.log(pid, "zotero_match", library=lib, backend=port.backend, items=n_items, matches=len(found))
        return {"library": lib, "items": n_items, "matches": len(found)}

    def review(self, pid: int, record_ids: list[int], verdict: str, rule_id: str | None = None,
               by: str | None = None) -> dict:
        """Ausgeblendete prüfen: zurückholen, als Grenzfall kennzeichnen oder Ausschluss bestätigen."""
        if verdict not in VERDICTS:
            raise ResearchError(f"Unbekannte Prüfung: {verdict}")
        p = self.store.project(pid)
        prefilters = {f["id"]: f for f in with_ids(p["prefilters"])}
        items = {it["id"]: it for it in self._pool_items(pid, p)[0]}
        by = by if by is not None else self.config.user_name
        done = 0
        for rid in record_ids:
            it = items.get(int(rid))
            if not it:
                continue
            rules = [rule_id] if rule_id else (it["hidden_by"] or it["matched_by"])
            labels = [prefilters[r]["label"] if r in prefilters else r for r in rules]
            for r in rules:
                self.store.set_review(pid, it["id"], r, verdict, by)
            current = self.store.current_decision(pid, it["id"])
            if verdict == "borderline":
                self.mark_borderline(pid, it["id"], True, "geprüft: " + "; ".join(labels), by)
            elif verdict == "exclude" and (not current or current["status"] == "open"):
                self.decide(pid, it["id"], "exclude", reason="Vorfilter: " + "; ".join(labels), by=by)
            done += 1
        self.store.log(pid, "review", verdict=verdict, rule=rule_id, records=done)
        return {"reviewed": done, "verdict": verdict}

    # -- Abstracts nachladen -------------------------------------------------------------------------
    @staticmethod
    def _needs_abstract(rec: dict, retry: bool = False) -> bool:
        """Noch nicht versucht – bzw. (retry) versucht, aber eine Quelle war nicht erreichbar oder überlastet."""
        data = rec.get("data") or {}
        if len((rec.get("abstract") or "").strip()) >= 50:
            return False
        return bool(data.get("abstract_failed")) if retry else not data.get("abstract_tried")

    def fetch_abstracts(self, pid: int, limit: int = 25, retry: bool = False) -> dict:
        """Fehlende Abstracts nachladen: Crossref (JATS), PubMed (PMID oder DOI), Semantic Scholar. Je Aufruf
        höchstens ``limit`` Datensätze; ohne Fund bleibt der Hinweis „nur Titel“ – nie ein Ausschluss. Fällt eine Quelle
        aus (Fehler, HTTP 429), merkt sich die App das; ``retry`` fragt später nur diese Quellen erneut."""
        todo = [r for r in self._records(pid) if self._needs_abstract(r, retry)][:limit]
        sources = ("Crossref", "PubMed", "Semantic Scholar")
        wanted = {r["id"]: set((r.get("data") or {}).get("abstract_failed") or sources) if retry else set(sources)
                  for r in todo}
        found: dict[int, tuple[str, str]] = {}
        failed: dict[int, set[str]] = {r["id"]: set() for r in todo}
        errors: list[str] = []
        cr = self.crossref()
        for r in todo:
            if r.get("doi") and "Crossref" in wanted[r["id"]]:
                try:
                    w = cr.work(r["doi"])
                except SourceError as e:
                    errors.append(str(e))
                    failed[r["id"]].add("Crossref")
                    continue
                if w and len(w.get("abstract") or "") >= 50:
                    found[r["id"]] = (w["abstract"], "Crossref")
        rest = [r for r in todo if r["id"] not in found and "PubMed" in wanted[r["id"]]]
        if rest:
            try:
                pm = self.pubmed()
                by_pmid = pm.by_pmids([r["pmid"] for r in rest if r.get("pmid")])
                by_doi = pm.by_dois([norm_doi(r["doi"]) for r in rest if r.get("doi") and not r.get("pmid")])
                for r in rest:
                    rec = by_pmid.get(r.get("pmid") or "") or by_doi.get(norm_doi(r.get("doi") or ""))
                    if rec and len(rec.get("abstract") or "") >= 50:
                        found[r["id"]] = (rec["abstract"], "PubMed")
            except SourceError as e:
                errors.append(str(e))
                for r in rest:
                    failed[r["id"]].add("PubMed")
        rest = [r for r in todo if r["id"] not in found and r.get("doi") and "Semantic Scholar" in wanted[r["id"]]]
        if rest:
            try:
                got = self.semanticscholar().abstracts([norm_doi(r["doi"]) for r in rest])
                for r in rest:
                    a = got.get(norm_doi(r["doi"]))
                    if a and len(a) >= 50:
                        found[r["id"]] = (a, "Semantic Scholar")
            except SourceError as e:
                errors.append(str(e))
                for r in rest:
                    failed[r["id"]].add("Semantic Scholar")
        by_source: Counter = Counter()
        for r in todo:
            data = dict(r.get("data") or {})
            if r["id"] in found:
                data["abstract"], data["abstract_source"] = found[r["id"]]
                by_source[data["abstract_source"]] += 1
                data.pop("abstract_failed", None)
            elif failed[r["id"]]:
                data["abstract_failed"] = sorted(failed[r["id"]])
            else:
                data.pop("abstract_failed", None)
            data["abstract_tried"] = True
            self.store.update_record_data(r["id"], data)
        records = self._records(pid)
        remaining = sum(1 for r in records if self._needs_abstract(r, retry))
        if retry:  # beim erneuten Versuch nicht endlos dieselben Treffer: was wieder scheitert, wartet auf das nächste Mal
            remaining = 0 if not found else remaining
        self.store.log(pid, "abstracts", checked=len(todo), filled=len(found), by_source=dict(by_source), retry=retry)
        return {"checked": len(todo), "filled": len(found), "by_source": dict(by_source), "remaining": remaining,
                "retry_possible": sum(1 for r in records if self._needs_abstract(r, True)),
                "errors": sorted(set(errors))[:3]}

    # -- Recall-Check ----------------------------------------------------------------------------------
    def set_key_papers(self, pid: int, text: str) -> dict:
        """Schlüsselarbeiten aus beliebigem Text (z. B. einer Markdown-Tabelle): jede DOI zählt."""
        dois = find_dois(text)
        self.update_project(pid, {"settings": {"key_papers": [{"doi": d} for d in dois]}})
        return self.recall(pid)

    def _recall(self, p: dict, items: list[dict]) -> list[dict]:
        papers = (p.get("settings") or {}).get("key_papers") or []
        by_doi = {norm_doi(it["doi"]): it for it in items if it["doi"]}
        labels = {f["id"]: f["label"] for f in with_ids(p["prefilters"])}
        out = []
        for kp in papers:
            doi = norm_doi(kp.get("doi", ""))
            it = by_doi.get(doi)
            if not it:
                out.append({"doi": doi, "status": "missing", "warn": True, "title": "",
                            "message": "nicht gefunden – kein Suchstring trifft diese Arbeit"})
                continue
            st = status_of(it)
            if it["hidden_by"] and not it["decision"]:
                status, warn = "hidden", True
                msg = "ausgeblendet durch " + "; ".join(labels.get(h, h) for h in it["hidden_by"])
            elif it["borderline"] and st == "open":
                status, warn, msg = "borderline", False, "Grenzfall – in der Warteschlange"
            elif st == "open":
                status, warn, msg = "visible", False, "sichtbar, noch nicht gesichtet"
            else:
                status, warn = st, False
                msg = {"include": "aufgenommen", "exclude": "ausgeschlossen", "maybe": "unsicher"}.get(st, st)
            out.append({"doi": doi, "status": status, "warn": warn, "message": msg, "record_id": it["id"],
                        "title": it["title"], "sources": it["sources"], "queries": it["queries"],
                        "zotero": bool(it["zotero_key"]), "no_abstract": it["no_abstract"]})
        return out

    def recall(self, pid: int) -> dict:
        p = self.store.project(pid)
        items, _ = self._pool_items(pid, p)
        rows = self._recall(p, items)
        return {"papers": rows, "warnings": sum(1 for r in rows if r["warn"])}

    # ------------------------------------------------------------------------------------------ Screening
    def queue(self, pid: int, status: str = "open") -> dict:
        """status: open | maybe | include | exclude | all | borderline (Grenzfälle) | hidden (ausgeblendet)."""
        p = self.store.project(pid)
        items, _ = self._pool_items(pid, p)
        visible = [it for it in items if not it["hidden_by"]]
        if status == "hidden":
            shown = [it for it in items if it["hidden_by"]]
        elif status == "borderline":
            shown = sorted((it for it in visible if it["borderline"]),
                           key=lambda it: (status_of(it) != "open", -it["borderline_strength"], it["id"]))
        elif status.startswith("ai_"):  # offene Treffer nach KI-Vorschlag: ai_include, ai_borderline, ai_exclude, ai_none
            want = status[3:]
            shown = [it for it in visible if status_of(it) == "open"
                     and ((it.get("ai") or {}).get("label") or "none") == want]
        elif status and status != "all":
            shown = [it for it in visible if status_of(it) == status]
        else:
            shown = visible
        return {"items": shown, "visible": len(visible),
                "counts": dict(Counter(status_of(it) for it in visible)),
                "ai_counts": dict(Counter((it.get("ai") or {}).get("label") or "none" for it in visible
                                          if status_of(it) == "open")),
                "borderline": sum(1 for it in visible if it["borderline"]),
                "hidden": len(items) - len(visible),
                "folders": p["folder_map"], "criteria_out": [x.strip() for x in p["criteria_out"].splitlines() if x.strip()]}

    METHODS = ("card", "list")

    def _decision_row(self, pid: int, rid: int, status: str, folder, reason: str, by: str | None,
                      borderline: bool | None, borderline_reason: str | None, ai: dict, ai_shown: bool | None,
                      method: str, batch: str = "") -> dict:
        if status not in STATUSES:
            raise ResearchError(f"Unbekannter Entscheid: {status}")
        if status == "include":
            if folder is None:
                raise ResearchError("Beim Aufnehmen fehlt der Ordner.")
            if int(folder) not in FOLDER_SLOTS:
                raise ResearchError(f"Ordner 1–{export_mod.MAX_FOLDERS}.")
        else:
            folder = None
        if method not in self.METHODS:
            raise ResearchError(f"Unbekannte Entscheidweise: {method}")
        current = self.store.current_decision(pid, rid)
        if borderline is None:  # das Kennzeichen bleibt beim nächsten Entscheid erhalten
            borderline = bool(current and current["borderline"])
            if borderline_reason is None:
                borderline_reason = current["borderline_reason"] if current else ""
        # Der damalige KI-Vorschlag gehört zum Entscheid – auch wenn er ausgeblendet war (dann ai_shown = 0)
        return dict(record_id=rid, status=status, folder=int(folder) if folder is not None else None, reason=reason or "",
                    by=by if by is not None else self.config.user_name, ai_suggestion=ai.get("label") or None,
                    ai_reason=ai.get("reason") or None, borderline=borderline, borderline_reason=borderline_reason or "",
                    ai_shown=ai_shown if ai.get("label") else None, method=method, batch=batch)

    def decide(self, pid: int, rid: int, status: str, folder: int | None = None, reason: str = "",
               by: str | None = None, borderline: bool | None = None, borderline_reason: str | None = None,
               ai_shown: bool | None = None, method: str = "card") -> dict:
        ai = self.store.ai_suggestions(pid).get(rid) or {}
        row = self._decision_row(pid, rid, status, folder, reason, by, borderline, borderline_reason, ai, ai_shown, method)
        return self.store.add_decisions(pid, [row])[0]

    def decide_bulk(self, pid: int, items: list[dict], ai_shown: bool | None = None, method: str = "list",
                    by: str | None = None) -> dict:
        """Sammel-Übernahme (Ansicht „Liste“): alle Entscheide als ein Stapel – „rückgängig“ nimmt ihn ganz zurück."""
        self.store.project(pid)
        if not items:
            raise ResearchError("Nichts zu übernehmen.")
        ai = self.store.ai_suggestions(pid)
        batch = f"b{int(time.time() * 1000):x}"
        rows = [self._decision_row(pid, int(x["record_id"]), x.get("status", ""), x.get("folder"), x.get("reason", ""), by,
                                   None, None, ai.get(int(x["record_id"])) or {}, ai_shown, method, batch) for x in items]
        saved = self.store.add_decisions(pid, rows)
        self.store.log(pid, "decisions_bulk", batch=batch, count=len(saved), method=method, ai_shown=ai_shown,
                       counts=dict(Counter(r["status"] for r in saved)))
        return {"batch": batch, "count": len(saved), "counts": dict(Counter(r["status"] for r in saved))}

    def move_folder(self, pid: int, src: int, dst: int) -> dict:
        """Aufgenommene Treffer von einem Ordner in einen anderen (z. B. bevor ein Ordner gelöscht wird). Als Stapel:
        „rückgängig“ nimmt die ganze Verschiebung zurück."""
        if src == dst or src not in FOLDER_SLOTS or dst not in FOLDER_SLOTS:
            raise ResearchError("Ungültige Ordner zum Verschieben.")
        current = [d for d in self.store.current_decisions(pid).values() if d["status"] == "include" and d["folder"] == src]
        if not current:
            return {"moved": 0}
        batch = f"m{int(time.time() * 1000):x}"
        self.store.add_decisions(pid, [{**{k: d[k] for k in ("record_id", "status", "reason", "by", "ai_suggestion", "ai_reason",
                                                                "borderline", "borderline_reason", "ai_shown", "method")},
                                        "folder": dst, "batch": batch} for d in current])
        self.store.log(pid, "folder_moved", src=src, dst=dst, count=len(current), batch=batch)
        return {"moved": len(current), "batch": batch}

    def mark_borderline(self, pid: int, rid: int, on: bool = True, reason: str = "", by: str | None = None) -> dict:
        """Kennzeichen „Grenzfall“ (Taste G) setzen oder entfernen; der Entscheid selbst bleibt."""
        current = self.store.current_decision(pid, rid)
        status = current["status"] if current else "open"
        return self.store.add_decision(pid, rid, status, current["folder"] if current else None,
                                       current["reason"] if current else "",
                                       by if by is not None else self.config.user_name,
                                       borderline=on, borderline_reason=reason if on else "")

    def undo(self, pid: int) -> dict | None:
        self.store.project(pid)
        return self.store.undo_decision(pid)

    # ------------------------------------------------------------------------------------------ KI-Vorschläge
    def ai_status(self) -> dict:
        if not self.chat:
            return {"available": False, "model": "", "message": "Kein Sprachmodell eingerichtet (Schlüssel für "
                    "Claude oder Gemini in ZotLLM speichern oder in config.ini unter [anthropic] bzw. [gemini] "
                    "eintragen, danach den Dienst neu starten)."}
        usage = dict(getattr(self.chat, "usage", {}) or {})
        model = getattr(self.chat, "model", "") or getattr(self.chat, "label", "")
        return {"available": True, "model": model, "label": getattr(self.chat, "label", model),
                "provider": getattr(self.chat, "provider", ""), "vendor": getattr(self.chat, "vendor", ""),
                "key_source": getattr(self.chat, "key_source", ""), "effort": getattr(self.chat, "effort", ""),
                "usage": usage, "cost": ai_mod.estimate_cost(model, usage), "used_total": ai_mod.used(model, usage),
                "prices": ai_mod.PRICES.get(model), "cost_per_record": ai_mod.estimate_cost(model, ai_mod.PER_RECORD)}

    def _model(self) -> str:
        return getattr(self.chat, "model", "") or getattr(self.chat, "label", "")

    def _snapshot(self) -> dict:
        return dict(getattr(self.chat, "usage", {}) or {})

    def _used_since(self, before: dict) -> dict:
        """Verbrauch dieses einen Aufrufs (der Adapter zählt seit Dienststart)."""
        after = self._snapshot()
        return ai_mod.used(self._model(), {k: after.get(k, 0) - before.get(k, 0) for k in after})

    def ai_estimate(self, pid: int, kind: str, blocks: list[dict] | None = None, parent: str = "") -> dict:
        """Geschätzte Token (und Kosten, falls der Preis bekannt ist) für einen KI-Vorschlag – vor dem Aufruf."""
        p = self.store.project(pid)
        if kind == "sources":
            text, schema = ai_mod.sources_system() + ai_mod.sources_prompt(p), ai_mod.sources_schema()
        elif kind == "blocks":
            text = ai_mod.blocks_system() + ai_mod.blocks_prompt(p, blocks if blocks is not None else self.store.blocks(pid))
            schema = ai_mod.BLOCKS_SCHEMA
        elif kind == "folders":
            items, _ = self._pool_items(pid, p)
            titles = [it["title"] for it in items if it["decision"] and it["decision"]["status"] == "include" and it["title"]][:60]
            text, schema = ai_mod.folders_system() + ai_mod.folders_prompt(p, export_mod.norm_path(parent), [], titles), ai_mod.FOLDERS_SCHEMA
        else:
            raise ResearchError(f"Unbekannte Schätzung: {kind}")
        return ai_mod.estimate(self._model() if self.chat else "", ai_mod.tokens(text) + ai_mod.schema_tokens(schema),
                               ai_mod.OUT_EST[kind])

    def _require_chat(self):
        if not self.chat:
            raise ResearchError(self.ai_status()["message"], "ai_missing")
        return self.chat

    AI_SCOPES = ("open", "borderline", "all")
    AI_REDO = ("", "failed", "all")  # nur neue | auch ohne gültige Antwort | auch mit Vorschlag

    @staticmethod
    def _ai_scope(items: list[dict], scope: str) -> list[dict]:
        visible = [it for it in items if not it["hidden_by"]]
        if scope == "borderline":
            visible = [it for it in visible if it["borderline"]]
        if scope in ("open", "borderline"):
            visible = [it for it in visible if status_of(it) == "open"]
        return visible

    def _ai_candidates(self, pid: int, scope: str, redo: str = "", since: str = "") -> list[dict]:
        """Noch nie gefragt; mit ``redo`` auch vor ``since`` Gefragte. Was im laufenden Durchgang schon gefragt wurde
        (at >= since), kommt nicht noch einmal – so endet jeder Durchgang, auch bei ungültigen Antworten."""
        items, _ = self._pool_items(pid)
        asked = self.store.ai_suggestions(pid)

        def todo(it):
            a = asked.get(it["id"])
            if a is None:
                return True
            if not redo or a["at"] >= since:
                return False
            return redo == "all" or not a["label"]

        return [it for it in self._ai_scope(items, scope) if todo(it)]

    def ai_plan(self, pid: int) -> dict:
        """Je Umfang: noch nicht gefragt (new), ohne gültige Antwort (failed), mit Vorschlag (done)."""
        self.store.project(pid)
        items, _ = self._pool_items(pid)
        asked = self.store.ai_suggestions(pid)

        def kind(it):
            a = asked.get(it["id"])
            return "new" if a is None else "done" if a["label"] else "failed"

        scopes = {}
        for scope in self.AI_SCOPES:
            sel = self._ai_scope(items, scope)
            c = Counter(kind(it) for it in sel)
            tok = Counter()
            for it in sel:
                tok[kind(it)] += ai_mod.item_tokens(it)
            scopes[scope] = {**{k: c[k] for k in ("new", "failed", "done")}, "tokens": {k: tok[k] for k in ("new", "failed", "done")}}
        p = self.store.project(pid)
        return {"scopes": scopes, "batch": ai_mod.BATCH, "system_tokens": ai_mod.screening_system_tokens(p),
                "out_per_record": ai_mod.OUT_PER_RECORD, **self.ai_status()}

    def ai_screen(self, pid: int, limit: int = ai_mod.BATCH, scope: str = "open", redo: str = "",
                  since: str | None = None) -> dict:
        """Ein Stapel KI-Vorschläge. Die Oberfläche ruft wieder (mit dem zurückgegebenen ``since``), bis ``remaining``
        null ist."""
        chat = self._require_chat()
        if scope not in self.AI_SCOPES:
            raise ResearchError(f"Unbekannter Umfang: {scope}")
        if redo not in self.AI_REDO:
            raise ResearchError(f"Unbekannte Wiederholung: {redo}")
        since = since or now()
        p = self.store.project(pid)
        todo = self._ai_candidates(pid, scope, redo, since)
        batch = todo[:max(1, min(limit, 50))]
        if not batch:
            return {"processed": 0, "remaining": 0, "counts": {}, "since": since, **self.ai_status()}
        ids = [it["id"] for it in batch]
        slots = {int(f["slot"]) for f in p["folder_map"] or []}
        before = self._snapshot()
        result = chat.complete_json(ai_mod.screening_system(p), ai_mod.screening_prompt(batch), ai_mod.SCREENING_SCHEMA)
        spent = self._used_since(before)
        rows = ai_mod.parse_screening(result, ids, slots)
        model = self._model()
        self.store.set_ai_suggestions(pid, rows, model)
        counts = dict(Counter(r["label"] or "keine Antwort" for r in rows))
        self.store.log(pid, "ai_screening", model=model, records=len(rows), counts=counts, used=spent)
        remaining = len(self._ai_candidates(pid, scope, redo, since))
        return {"processed": len(rows), "remaining": remaining, "counts": counts, "since": since, "used": spent,
                **self.ai_status()}

    def ai_sources(self, pid: int) -> dict:
        """Vorschlag für Disziplinen und Datenbanken aus dem Projekttext – wird nicht gespeichert."""
        chat = self._require_chat()
        p = self.store.project(pid)
        if not (p.get("question") or p.get("description") or "").strip():
            raise ResearchError("Für einen Vorschlag braucht es eine Fragestellung oder Kurzbeschreibung (Projekt).")
        before = self._snapshot()
        out = ai_mod.parse_sources(chat.complete_json(ai_mod.sources_system(), ai_mod.sources_prompt(p),
                                                      ai_mod.sources_schema()))
        spent = self._used_since(before)
        self.store.log(pid, "ai_sources", model=self._model(), sources=[s["id"] for s in out["sources"]], used=spent)
        return {**out, "used": spent, **self.ai_status()}

    def ai_blocks(self, pid: int, blocks: list[dict] | None = None, focus: dict | None = None) -> dict:
        """Vorschlag für Konzeptblöcke aus dem Projekttext; ``blocks``: die Blöcke, wie sie gerade in der Oberfläche
        stehen (sonst die gespeicherten). ``focus`` ({name, kind, terms, hint}): nur diesen einen Block neu vorschlagen.
        Wird nicht gespeichert."""
        chat = self._require_chat()
        p = self.store.project(pid)
        if not (p.get("question") or p.get("description") or "").strip():
            raise ResearchError("Für einen Vorschlag braucht es eine Fragestellung oder Kurzbeschreibung (Projekt).")
        existing = blocks if blocks is not None else self.store.blocks(pid)
        before = self._snapshot()
        prompt = ai_mod.blocks_prompt(p, existing) + (ai_mod.blocks_focus(focus) if focus else "")
        out = ai_mod.parse_blocks(chat.complete_json(ai_mod.blocks_system(), prompt, ai_mod.BLOCKS_SCHEMA))
        if focus:  # genau ein Block, unter dem bisherigen Namen
            name = str(focus.get("name") or "").strip()
            same = [b for b in out["blocks"] if b["name"].lower() == name.lower()] or out["blocks"][:1]
            out["blocks"] = [{**b, "name": name or b["name"]} for b in same[:1]]
        spent = self._used_since(before)
        self.store.log(pid, "ai_blocks", model=self._model(), blocks=[b["name"] for b in out["blocks"]], used=spent)
        return {**out, "used": spent, **self.ai_status()}

    def ai_folders(self, pid: int, parent: str = "", lib: str | None = None, backend: str | None = None) -> dict:
        """Vorschlag für 3–6 Untersammlungen unter ``parent`` (Pfad) – nur Vorschlag, angelegt wird nichts."""
        chat = self._require_chat()
        p = self.store.project(pid)
        if not (p.get("question") or p.get("description") or "").strip():
            raise ResearchError("Für einen Vorschlag braucht es eine Fragestellung oder Kurzbeschreibung (Projekt).")
        parent = export_mod.norm_path(parent)
        children: list[str] = []
        try:
            paths = export_mod.collection_paths(self.zotero_port(backend or p["zotero_backend"]).collections(lib or p["target_library"]))
            children = sorted({path[len(parent) + 1:].split("/")[0] if parent else path.split("/")[0]
                               for path in paths if (path.startswith(parent + "/") if parent else True)})
        except ResearchError:
            pass  # Zotero nicht erreichbar: Vorschlag ohne Kenntnis der vorhandenen Sammlungen
        items, _ = self._pool_items(pid, p)
        titles = [it["title"] for it in items if it["decision"] and it["decision"]["status"] == "include" and it["title"]][:60]
        before = self._snapshot()
        out = ai_mod.parse_folders(chat.complete_json(ai_mod.folders_system(), ai_mod.folders_prompt(p, parent, children, titles),
                                                      ai_mod.FOLDERS_SCHEMA), children)
        spent = self._used_since(before)
        self.store.log(pid, "ai_folders", model=self._model(), parent=parent, folders=[f["name"] for f in out["folders"]], used=spent)
        return {"parent": parent, "existing": children, **out, "used": spent, **self.ai_status()}

    # ------------------------------------------------------------------------------------------ Zotero-Sammlungen
    def zotero_tree(self, backend: str, lib: str) -> dict:
        """Sammlungen einer Bibliothek als Baum (wie in Zotero sortiert), je mit Pfad für die Ordner-Zuordnung."""
        cols = self.zotero_port(backend).collections(lib)
        by_parent: dict[str | None, list[dict]] = {}
        for c in cols:
            by_parent.setdefault(c.get("parent") or None, []).append(c)
        keys = {c["key"] for c in cols}

        def build(parent_key, prefix, depth=0):
            kids = sorted(by_parent.get(parent_key, []), key=lambda c: c["name"].casefold())
            return [{"key": c["key"], "name": c["name"], "path": f"{prefix}{c['name']}",
                     "children": build(c["key"], f"{prefix}{c['name']}/", depth + 1) if depth < 20 else []} for c in kids]

        roots = build(None, "") + [n for c in cols if c.get("parent") and c["parent"] not in keys  # verwaiste: oben zeigen
                                   for n in [{"key": c["key"], "name": c["name"], "path": c["name"], "children": []}]]
        return {"lib": lib, "collections": roots}

    def create_collections(self, pid: int, paths: list[str], confirm: bool = False) -> dict:
        """Sammlungen in der Zielbibliothek anlegen (nur nach ausdrücklicher Bestätigung); vorhandene bleiben."""
        if not confirm:
            raise ZoteroWriteRefused("Nach Zotero wird nur nach ausdrücklicher Bestätigung geschrieben.")
        p = self.store.project(pid)
        port, lib = self.zotero_port(p["zotero_backend"]), p["target_library"]
        if not port.can_write(lib):
            raise ZoteroWriteRefused("Kein Schreibzugriff auf die Zielbibliothek (Schlüssel oder Freigabe fehlt).")
        known = export_mod.collection_paths(port.collections(lib))
        before = set(known)
        for path in dict.fromkeys(export_mod.norm_path(x) for x in paths or []):
            if path:
                export_mod.ensure_path(port, lib, path, known)
        created = sorted(set(known) - before)
        self.store.log(pid, "zotero_collections", library=lib, created=created)
        return {"created": created, "library": lib}

    # ------------------------------------------------------------------------------------------ Übergabe
    def export_plan(self, pid: int, backend: str | None = None) -> dict:
        p = self.store.project(pid)
        port = self.zotero_port(backend or p["zotero_backend"])
        out = export_mod.plan(self.store, pid, port)
        out["can_write"] = port.can_write(p["target_library"])
        return out

    def export(self, pid: int, backend: str | None = None, confirm: bool = False, crossref: bool = True) -> dict:
        p = self.store.project(pid)
        port = self.zotero_port(backend or p["zotero_backend"])
        return export_mod.execute(self.store, pid, port, confirm=confirm,
                                  crossref=self.crossref() if crossref else None)

    def protocol(self, pid: int, kind: str = "md") -> tuple[str, str, str]:
        """(Inhalt, Dateiname, MIME-Typ)"""
        p = self.store.project(pid)
        slug = "".join(ch if ch.isalnum() else "_" for ch in p["title"]).strip("_")[:50] or f"projekt_{pid}"
        if kind == "md":
            return protocol.markdown(self, pid), f"Suchprotokoll_{slug}.md", "text/markdown"
        if kind == "runs":
            return protocol.runs_csv(self.store, pid), f"Suchen_{slug}.csv", "text/csv"
        if kind == "records":
            return protocol.records_csv(self, pid), f"Treffer_{slug}.csv", "text/csv"
        raise NotFound(f"Unbekanntes Protokoll: {kind}")


def clean_folder_map(folders: list[dict]) -> list[dict]:
    out = []
    for f in folders or []:
        try:
            slot = int(f.get("slot"))
        except (TypeError, ValueError):
            continue
        if slot not in FOLDER_SLOTS or not (f.get("path") or f.get("label")):
            continue
        out.append({"slot": slot, "label": (f.get("label") or "").strip(), "path": export_mod.norm_path(f.get("path", ""))})
    return sorted(out, key=lambda f: f["slot"])
