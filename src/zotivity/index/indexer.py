"""Abgleich mit Zotero, Textextraktion und Embedding.

Ablauf eines Indexierlaufs:
1. Metadaten-Abgleich der Bibliotheken, die in Wissenskorpora vorkommen.
2. Dokument für Dokument: Text + Seitenzahlen extrahieren, in Abschnitte zerlegen,
   Abschnitte einbetten – mit Fortschritt pro Dokument (Abschnitte/Prozent).
3. Abschluss: übrige Abschnitte (z. B. Abstracts von Einträgen ohne PDF).
Jederzeit abbrech- und wiederaufnehmbar – der Zustand liegt in der Datenbank.

Für grosse Bibliotheken (Tausende PDFs, Läufe über Tage):
- Texte werden in einem eigenen Prozess mit Zeitlimit gelesen (defekte Dateien reissen nichts mit).
- Fällt der Embedding-Dienst aus, wartet der Lauf (bis zu outage_wait_minutes) statt abzubrechen.
- Der Rechner bleibt wach; vor dem Start wird der Speicherplatz geprüft, danach der Index gesichert.
- Hintergrundläufe können auf ein Zeitfenster und eine Höchstzahl Texte begrenzt werden (Etappen).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from zotivity import paths
from zotivity.embeddings import EmbeddingError
from zotivity.engine import Engine
from zotivity.extract import chunk_pages, extract_file, make_abstract_chunk, text_as_document
from zotivity.extract.chunker import mark_references
from zotivity.extract.pagenumbers import parse_page_range
from zotivity.extract.worker import DEFAULT_TARGET, ExtractionFailed, ExtractionWorker
from zotivity.index import duplicates
from zotivity.index.store import SearchFilter, strip_bidi
from zotivity.index.vectors import normalize
from zotivity.jobs import Job, JobCancelled
from zotivity.power import keep_awake
from zotivity.zotero import ZoteroError, ZoteroUnavailable

BACKUP_EVERY_HOURS = 12
BACKUPS_KEPT = 2
MB_PER_DOCUMENT = 0.6  # Text, Volltextindex und Vektoren je PDF (grob, eher grosszügig)
MODEL_SWITCHED = ("Das Embedding-Modell wurde während des Laufs gewechselt – Lauf beendet. Bereits Verarbeitetes "
                  "bleibt erhalten; der nächste Lauf arbeitet mit dem neuen Modell.")


class EmbeddingSwitched(Exception):
    """Das Embedding-Modell (der Vektorraum) hat sich mitten im Lauf geändert."""


def author_year(item: dict) -> str:
    from zotivity.rag.sources import author_year as _ay

    return _ay(item)

log = logging.getLogger(__name__)


def file_stat(path: Path | None) -> dict:
    """Grösse und Änderungszeit zum Zeitpunkt der Verarbeitung (für die Änderungserkennung)."""
    try:
        st = path.stat() if path else None
    except OSError:
        st = None
    return {"file_size": st.st_size, "file_mtime": st.st_mtime} if st else {}


def file_md5(path: Path) -> str | None:
    h = hashlib.md5()  # noqa: S324 - Vergleich mit der MD5-Summe, die Zotero führt
    try:
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def in_hour_window(now: datetime, start: int | None, end: int | None) -> bool:
    """Liegt `now` im Zeitfenster [start, end)? Über Mitternacht möglich (22 → 7). Ohne Angabe: immer."""
    if start is None or end is None or start == end:
        return True
    h = now.hour
    return start <= h < end if start < end else (h >= start or h < end)


def window_end(now: datetime, start: int | None, end: int | None) -> float | None:
    """Zeitpunkt (Unix-Zeit), an dem das laufende Zeitfenster endet."""
    if start is None or end is None or start == end:
        return None
    stop = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if stop <= now:
        stop += timedelta(days=1)
    return stop.timestamp()


def embedding_text(chunk: dict, item: dict | None, with_header: bool) -> str:
    """Text, der eingebettet wird – optional mit Kontextkopf (Autor, Jahr, Titel)."""
    if not with_header or not item:
        return chunk["text"]
    head = []
    if item.get("creator_summary"):
        head.append(strip_bidi(item["creator_summary"]))
    if item.get("year"):
        head.append(f"({item['year']})")
    title = item.get("title") or ""
    header = " ".join(head) + (": " if head else "") + title
    if chunk.get("kind") == "abstract":
        header = "Abstract – " + header
    return f"{header}\n\n{chunk['text']}" if header.strip() else chunk["text"]


class Indexer:
    def __init__(self, engine: Engine):
        self.engine = engine
        # Funktion, die im Lese-Prozess läuft (für Tests austauschbar)
        self.worker_target = DEFAULT_TARGET

    @property
    def store(self):
        return self.engine.store

    # ------------------------------------------------------------------------------
    # 1. Metadaten
    # ------------------------------------------------------------------------------
    FULL_SYNC_DAYS = 7

    def sync_metadata(self, job: Job | None = None, full: bool = False, libraries: list[str] | None = None) -> dict:
        """Abgleich mit Zotero (nur die Bibliotheken, die in Korpora vorkommen).

        - Erster Abgleich (oder `full`, oder alle 7 Tage): alle Einträge laden.
        - Danach: neue und gelöschte Einträge über die Schlüsselliste (billig), lokal geänderte
          über `since`, geänderte PDF-Dateien über Grösse/Änderungszeit auf der Festplatte.
          Das funktioniert auch für Gruppenbibliotheken, für die Zotero 10 die Version 0 meldet,
          und vermeidet, dass Zotero bei jedem Lauf MD5-Summen aller PDFs berechnet.
        """
        zot = self.engine.zotero()
        if not zot.is_available(fresh=True):
            raise ZoteroUnavailable("Zotero ist nicht erreichbar oder die lokale API ist deaktiviert.")
        server_id = zot.server_id
        summary = {"items": 0, "attachments": 0, "deleted": 0, "changed_files": 0}
        group_names: dict[str, str] | None = None
        if libraries is None:
            libraries = self.engine.libraries_of(self.engine.corpus_sources())

        for lib in libraries:
            state = self.store.library_state(lib)
            if state.get("server_id") and state["server_id"] != server_id:
                log.warning("Andere Zotero-Instanz erkannt (%s) – vollständiger Abgleich", lib)
                self.store.reset_library(lib)
                state = self.store.library_state(lib)
            name = state.get("name")
            if not name:
                if lib.startswith("groups/"):
                    if group_names is None:
                        try:
                            group_names = {f"groups/{g['id']}": g["data"].get("name", "") for g in zot.groups()}
                        except ZoteroError:
                            group_names = {}
                    name = group_names.get(lib) or lib
                else:
                    name = "Meine Bibliothek"
            since = int(state.get("items_version") or 0)
            version, total = zot.library_stamp(lib)
            now = time.time()
            do_full = (full or not state.get("synced_at") or not state.get("full_synced_at")
                       or now - state["full_synced_at"] > self.FULL_SYNC_DAYS * 86400)
            if job:
                job.update(phase="Abgleich", message=f"{name}: Sammlungen")
            self.store.replace_collections(lib, zot.collections(lib))

            # Schlüssel aller Einträge und Anhänge (ohne Notizen/Annotationen)
            alive = set(zot.item_keys(lib, exclude_types=["note", "annotation"]))
            known = self.store.item_keys(lib) | self.store.attachment_keys(lib)

            fetched: list[dict] = []
            if do_full:
                if job:
                    job.update(message=f"{name}: alle Einträge laden")
                fetched = list(self._iter_checked(zot.iter_items(lib), job))
            else:
                if version > since:
                    if job:
                        job.update(message=f"{name}: geänderte Einträge seit Version {since}")
                    fetched = list(self._iter_checked(zot.iter_items(lib, since=since), job))
                new_keys = alive - known - {it["key"] for it in fetched}
                if new_keys:
                    if job:
                        job.update(message=f"{name}: {len(new_keys)} neue Einträge laden")
                    fetched += list(self._iter_checked(zot.iter_items(lib, keys=sorted(new_keys)), job))

            counts = self._store_items(lib, fetched)
            summary["items"] += counts["items"]
            summary["attachments"] += counts["attachments"]

            # Anhänge, die früher als nicht lesbar übersprungen wurden (z. B. Word vor 0.9.0): jetzt vormerken
            for key in self.store.skipped_attachments(lib, self.engine.settings.indexing.content_types):
                try:
                    p = zot.file_path(lib, {"key": key})
                except ZoteroError:
                    continue
                self.store.activate_attachment(lib, key, str(p) if p else None)
                summary["attachments"] += 1

            # Geänderte Dateien (z. B. ersetzte PDF) – ohne Zotero, direkt über das Dateisystem.
            # Hat sich nur die Änderungszeit geändert (z. B. Datenordner kopiert), entscheidet die Prüfsumme –
            # so wird nach einem Umzug nicht die ganze Bibliothek neu indexiert.
            refetched = {it["key"] for it in fetched}
            changed = []
            for att in self.store.processed_attachments(lib):
                if att["key"] in refetched or att["file_size"] is None:
                    continue
                path = Path(att["path"])
                try:
                    st = path.stat()
                except OSError:
                    continue
                if st.st_size != att["file_size"]:
                    changed.append(att["key"])
                elif abs(st.st_mtime - (att["file_mtime"] or 0)) > 2:
                    if att.get("indexed_md5") and file_md5(path) == att["indexed_md5"]:
                        self.store.set_file_stat(lib, att["key"], st.st_size, st.st_mtime)
                    else:
                        changed.append(att["key"])
            if changed:
                self.store.mark_pending(lib, changed)
                summary["changed_files"] += len(changed)

            # Gelöschte/in den Papierkorb verschobene Einträge entfernen
            gone_items = self.store.item_keys(lib) - alive
            gone_atts = self.store.attachment_keys(lib) - alive
            if gone_atts:
                self.store.delete_attachments(lib, gone_atts)
            if gone_items:
                self.store.delete_items(lib, gone_items)
            summary["deleted"] += len(gone_items) + len(gone_atts)
            if gone_items or gone_atts:
                self.engine.reset_vector_index()

            values = {"server_id": server_id, "items_version": version, "synced_at": now, "name": name,
                      "items_total": total}
            if do_full:
                values["full_synced_at"] = now
            self.store.set_library_state(lib, **values)
        if summary["deleted"]:
            # Gelöschte Einträge, die ein Forschungsstand oder eine Antwort zitiert: auf eine Kopie umstellen
            try:
                from zotivity import references

                references.repair(self.engine, fetch=False)
            except Exception:  # noqa: BLE001 - der Abgleich selbst ist gelungen
                log.exception("Belege auf gelöschte Einträge nicht umgestellt")
        return summary

    def catalog_changes(self) -> list[str]:
        """Bibliotheken, die Zotero seit dem letzten Abgleich geändert hat: Zotero zählt je Bibliothek eine
        Versionsnummer hoch (jede Änderung, auch an Notizen und Markierungen); gespeichert ist die beim Abgleich.
        Gruppen melden in Zotero 10 lokal keine Version – dort zeigt die Zahl der Einträge neue und gelöschte
        Einträge (geänderte Felder nicht; die holt der stündliche Abgleich). Neue Gruppen zählen ebenfalls.
        Kostet je Bibliothek eine kleine Anfrage."""
        zot = self.engine.zotero()
        libraries = ["users/0"] + [f"groups/{g['id']}" for g in zot.groups()]
        return [lib for lib in libraries if self.library_changed(zot, lib)]

    def library_changed(self, zot, lib: str) -> bool:
        state = self.store.library_state(lib)
        if not state.get("synced_at"):
            return True
        version, total = zot.library_stamp(lib)
        if version:
            return version > int(state.get("items_version") or 0)
        return total != int(state.get("items_total") or 0)

    def sync_catalog(self, job: Job | None = None, full: bool = False) -> dict:
        """Suchkatalog: Metadaten ALLER Bibliotheken (eigene und Gruppen) abgleichen – ohne Texte einzulesen.
        Danach kennt Zotivity auch Einträge ausserhalb der Korpora (Suche, Vorschau neuer Korpora)."""
        zot = self.engine.zotero()
        if not zot.is_available(fresh=True):
            raise ZoteroUnavailable("Zotero ist nicht erreichbar oder die lokale API ist deaktiviert.")
        libraries = ["users/0"] + [f"groups/{g['id']}" for g in zot.groups()]
        names = {f"groups/{g['id']}": g["data"].get("name", "") for g in zot.groups()}
        for lib, name in names.items():
            if name and self.store.library_state(lib).get("name") != name:
                self.store.set_library_state(lib, name=name)
        if job:
            job.update(phase="Suchkatalog", total=len(libraries), done=0)
        summary = {"libraries": len(libraries), "items": 0, "attachments": 0, "deleted": 0}
        for i, lib in enumerate(libraries):
            if job:
                job.check()
                job.update(message=f"{names.get(lib) or 'Meine Bibliothek'} ({i + 1} von {len(libraries)})")
            s = self.sync_metadata(job, full=full, libraries=[lib])
            for k in ("items", "attachments", "deleted"):
                summary[k] += s.get(k, 0)
            if job:
                job.update(done=i + 1)
        self.store.set_meta("catalog_synced_at", str(time.time()))
        if job:
            job.update(phase="Fertig", message=f"{len(libraries)} Bibliotheken abgeglichen")
        return summary

    def reconcile_snapshots(self) -> None:
        """Schnappschüsse neben einer lesbaren PDF/EPUB überspringen (kein doppelter Text im Index)."""
        if self.store.reconcile_snapshots():
            self.engine.reset_vector_index()

    @staticmethod
    def _iter_checked(items, job: Job | None):
        for it in items:
            if job:
                job.check()
            yield it

    def _store_items(self, lib: str, items: list[dict]) -> dict:
        zot = self.engine.zotero()
        content_types = set(self.engine.settings.indexing.content_types)
        regular = [it for it in items if it.get("data", {}).get("itemType") not in ("attachment", "note", "annotation")]
        out = {"items": self.store.upsert_items(lib, regular), "attachments": 0}
        for att in (it for it in items if it.get("data", {}).get("itemType") == "attachment"):
            d = att.get("data", {})
            if not d.get("parentItem"):
                # Eigenständiger Anhang: als eigener Eintrag führen
                self.store.upsert_items(lib, [att])
            supported = d.get("linkMode") != "linked_url" and d.get("contentType") in content_types
            path = None
            if supported:
                try:
                    p = zot.file_path(lib, att)
                    path = str(p) if p else None
                except ZoteroError:
                    path = None
            self.store.upsert_attachment(lib, att, path, supported=supported)
            out["attachments"] += 1
        return out

    # ------------------------------------------------------------------------------
    # Umfang: was indexiert wird, bestimmen die Wissenskorpora
    # ------------------------------------------------------------------------------
    def sources_for(self, corpus_id: int | None = None, collections: list[str] | None = None) -> list[str]:
        if collections is not None:
            return list(collections)
        return self.engine.corpus_sources(corpus_id)

    def scope(self, extra_items: list[str] | None = None, collections: list[str] | None = None,
              corpus_id: int | None = None, resolve: bool = True) -> set[tuple[str, str]]:
        """Menge (lib, item_key) im Umfang (alle Korpora, ein Korpus oder explizite Quellen).
        resolve: Dubletten durch die gewählte Kopie ersetzen (sonst die Einträge, wie sie in den Sammlungen stehen)."""
        f = SearchFilter(collections=self.sources_for(corpus_id, collections), item_keys=extra_items or [])
        if f.is_empty():
            return set()
        raw = self.store.allowed_items(f) or set()
        return self.engine.resolve_copies(raw) if resolve else raw

    # ------------------------------------------------------------------------------
    # 2. Extraktion
    # ------------------------------------------------------------------------------
    def extract_one(self, att: dict, worker: ExtractionWorker | None = None, check=None) -> tuple[str, str]:
        """Extrahiert einen Anhang (im Lese-Prozess, falls `worker` gegeben). Rückgabe (status, meldung)."""
        settings = self.engine.settings
        icfg, ccfg = settings.indexing, settings.chunking
        lib, key, parent = att["lib"], att["key"], att["parent"]
        doc = None
        warning = ""
        path = Path(att["path"]) if att.get("path") else None
        stat = file_stat(path)
        if path and path.exists():
            kwargs = {"max_pages": icfg.max_pages_per_document, "min_chars_per_page": icfg.min_chars_per_page,
                      "ocr": icfg.ocr, "ocr_languages": icfg.ocr_languages}
            # Seitenspanne laut Zotero (z. B. 114–126) als Gegenprobe für die gedruckten Seitenzahlen
            page_range = parse_page_range(((self.store.item(lib, parent) or {}).get("data") or {}).get("pages"))
            if page_range:
                kwargs["page_range"] = page_range
            try:
                if worker is not None:
                    doc = worker.call(path, att.get("content_type") or "", timeout=icfg.extract_timeout_seconds,
                                      check=check, **kwargs)
                else:
                    doc = extract_file(path, att.get("content_type") or "", **kwargs)
                warning = "; ".join(doc.warnings)
            except ExtractionFailed as e:
                warning = str(e)
                doc = None
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ == "JobCancelled":
                    raise
                warning = f"Datei nicht lesbar: {e}"
                doc = None
        elif path:
            warning = "Datei nicht vorhanden (nicht synchronisiert?)"
        else:
            warning = "Kein Dateipfad"

        if (doc is None or doc.needs_ocr or doc.char_count == 0) and icfg.use_zotero_fulltext_fallback:
            try:
                text = self.engine.zotero().fulltext(lib, key)
            except ZoteroError:
                text = None
            if text and len(text) > 200:
                doc = text_as_document(text, "zotero-fulltext")
                warning = (warning + "; " if warning else "") + "Zotero-Volltext verwendet (ohne Seitenzahlen)"

        if doc is None:
            self.store.set_attachment_status(lib, key, "error", error=warning or "Unbekannter Fehler",
                                             indexed_md5=att.get("md5"), indexed_at=time.time(), **stat)
            return "error", warning
        if doc.needs_ocr or doc.char_count < 200:
            self.store.replace_chunks(lib, parent, key, [])
            msg = "Scan ohne Textebene – Texterkennung (OCR) nötig" if doc.needs_ocr else "Kein Text gefunden"
            self.store.set_attachment_status(lib, key, "no_text", error=msg, method=doc.method,
                                             n_pages=doc.n_pages, n_chars=doc.char_count, n_chunks=0,
                                             indexed_md5=att.get("md5"), indexed_at=time.time(), **stat)
            return "no_text", msg

        chunks = mark_references(chunk_pages(doc.pages, chunk_tokens=ccfg.chunk_tokens,
                                             overlap_tokens=ccfg.overlap_tokens,
                                             min_chunk_tokens=ccfg.min_chunk_tokens))
        self.store.replace_chunks(lib, parent, key, chunks)
        # Gedruckte Seitenzahl je PDF-Seite ("" = ohne) – für Seitenangaben in Belegen und deren Links
        labels = [p.label for p in doc.pages] if doc.method in ("pymupdf", "ocr") else []
        self.store.set_attachment_status(lib, key, "indexed", error=warning or None, method=doc.method,
                                         n_pages=doc.n_pages, n_chars=doc.char_count, n_chunks=len(chunks),
                                         indexed_md5=att.get("md5"), indexed_at=time.time(),
                                         page_labels=json.dumps(labels, ensure_ascii=False),
                                         label_source=getattr(doc, "label_source", "") or "", **stat)
        return "indexed", warning

    def sync_abstracts(self, scope) -> int:
        if not self.engine.settings.chunking.index_abstracts:
            return 0
        n = 0
        rows = self.store.con.execute("SELECT lib, key, abstract FROM items").fetchall()
        for r in rows:
            if scope is not None and (r["lib"], r["key"]) not in scope:
                continue
            self.store.sync_abstract_chunk(r["lib"], r["key"], make_abstract_chunk(r["abstract"]))
            n += 1
        return n

    # ------------------------------------------------------------------------------
    # 3. Embedding
    # ------------------------------------------------------------------------------
    def _embed_rows(self, rows: list[dict], job: Job | None, space: str | None = None) -> int:
        """Bettet eine Gruppe von Abschnitten ein (mit Wiederholung bei kurzen Ausfällen).
        space: Vektorraum des Laufs. Wurde das Modell inzwischen gewechselt, nichts speichern (EmbeddingSwitched) –
        sonst landeten die Vektoren im neuen Raum, während der Lauf weiter die Lücken im alten sucht."""
        settings = self.engine.settings
        emb = self.engine.embedder()
        space = space or emb.space_id
        if emb.space_id != space:
            raise EmbeddingSwitched()
        items = self.store.items({(r["lib"], r["item_key"]) for r in rows})
        texts = [embedding_text(r, items.get((r["lib"], r["item_key"])), settings.chunking.metadata_header)
                 for r in rows]
        vecs = None
        waited, attempt = 0.0, 0
        max_wait = settings.embedding.outage_wait_minutes * 60
        phase = job.phase if job else ""
        while vecs is None:
            try:
                vecs = emb.embed_documents(texts)
            except EmbeddingError as e:
                # Dauerhafte Fehler (Schlüssel, Modell fehlt) sofort melden; Ausfälle überbrücken
                if not e.transient or waited >= max_wait or job is None:
                    raise
                pause = min(5 * 2 ** attempt, 60, max(1.0, max_wait - waited))
                attempt += 1
                job.update(phase="Warte auf Embedding-Dienst",
                           message=f"{e} – neuer Versuch in {int(pause)} s (wartet seit {int(waited)} s)")
                job.note(f"Embedding-Dienst nicht verfügbar: {e}")
                job.sleep(pause)
                waited += pause
                emb = self.engine.embedder()
                if emb.space_id != space:
                    raise EmbeddingSwitched()
        if attempt and job:
            job.update(phase=phase)
            job.note(f"Embedding-Dienst wieder erreichbar (nach {int(waited)} s)")
        vecs = normalize(vecs).astype(np.float16)
        ids = [r["id"] for r in rows]
        current, vindex = self.engine.vector_index()
        if current != space:  # während dieses Pakets gewechselt: Vektoren des alten Modells verwerfen
            raise EmbeddingSwitched()
        self.store.put_embeddings(space, ids, vecs)
        vindex.add(ids, vecs)
        return len(rows)

    # ------------------------------------------------------------------------------
    # Gesamtlauf – Dokument für Dokument, mit genauer Fortschrittsmeldung
    # ------------------------------------------------------------------------------
    def run(self, job: Job, *, sync: bool = True, collections: list[str] | None = None,
            items: list[str] | None = None, retry_errors: bool = False, full_sync: bool = False,
            corpus_id: int | None = None, deadline: float | None = None, max_docs: int = 0,
            trigger: str = "manual", embed_only: bool = False) -> dict:
        """deadline/max_docs: Etappe beenden, wenn das Zeitfenster vorbei bzw. so viele Texte verarbeitet sind.
        trigger: "manual" oder "background" (für den Verlauf der Läufe).
        embed_only: nur gelesene Texte für das aktive Modell einbetten, keinen Text (neu) lesen."""
        lock = self.engine.index_lock
        if not lock.acquire(blocking=False):
            raise RuntimeError("Es läuft bereits eine Indexierung.")
        settings = self.engine.settings
        worker = ExtractionWorker(self.worker_target) if settings.indexing.isolate_extraction else None
        job.counters["trigger"] = trigger
        processed: list[dict] = []
        result: dict = {}
        status, error = "done", None
        try:
            with keep_awake(settings.indexing.keep_awake):
                result = self._run(job, sync=sync, collections=collections, items=items, retry_errors=retry_errors,
                                   full_sync=full_sync, corpus_id=corpus_id, deadline=deadline, max_docs=max_docs,
                                   worker=worker, processed=processed, embed_only=embed_only)
            if result.get("extracted") or result.get("errors") or result.get("no_text"):
                self.maybe_backup(job)
            if result.get("stopped"):
                status = "switched" if result.get("switched") else "stage"
            return result
        except JobCancelled:
            status = "cancelled"
            raise
        except Exception as e:
            status, error = "error", str(e) or type(e).__name__
            raise
        finally:
            self.store.busy = None
            if worker is not None:
                worker.stop()
            lock.release()
            try:
                self.record_run(job, trigger, status, error, result, processed, corpus_id)
            except Exception:  # noqa: BLE001 - der Verlauf darf den Lauf nicht verderben
                log.exception("Indexierlauf nicht im Verlauf gespeichert")

    def record_run(self, job: Job, trigger: str, status: str, error: str | None, result: dict,
                   processed: list[dict], corpus_id: int | None) -> int | None:
        """Lauf im Verlauf speichern – nur, wenn er etwas getan hat oder scheiterte (reine Prüfungen nicht)."""
        now = time.time()
        self.store.set_meta("index_checked_at", str(now))
        c = job.counters
        chunks = int(c.get("chunks_embedded") or 0)
        # Für die Meldung am Ende (Oberfläche): Probleme, nur eingebettete Texte und Etappe
        c["problems"] = sum(1 for d in processed if d["status"] not in ("indexed", "embedded"))
        c["embedded_docs"] = sum(1 for d in processed if d["status"] == "embedded")
        c["read_docs"] = sum(1 for d in processed if d["status"] == "indexed")
        c["stopped"] = result.get("stopped")
        if status == "done" and not processed and not chunks:
            return None
        model = c.get("model") or self.engine.embedding_label()
        run = {
            "started_at": job.started_at, "finished_at": now, "status": status, "trigger": trigger, "title": job.title,
            "corpus_id": corpus_id, "docs_total": int(c.get("docs_total") or 0), "docs_done": len(processed),
            "indexed": c["read_docs"], "embedded_docs": c["embedded_docs"],
            "no_text": sum(1 for d in processed if d["status"] == "no_text"),
            "errors": sum(1 for d in processed if d["status"] == "error"),
            "chunks": chunks, "stopped": result.get("stopped"), "error": error, "model": model,
        }
        rid = self.store.add_index_run(run, processed[:3000], list(job.log))
        c["run_id"] = rid
        # Gemessene Einbett-Rate je Modell merken (für Zeitschätzungen, z. B. nach einem Modellwechsel) – beim Modell
        # des Laufs, nicht bei einem, auf das inzwischen gewechselt wurde
        space = c.get("space") or self.engine.embedding_status().get("space")
        if space and chunks >= 20 and c.get("embed_rate"):
            self.store.set_meta(f"embed_rate:{space}", str(c["embed_rate"]))
        return rid

    # -- Sicherung und Speicherplatz -------------------------------------------------------
    @staticmethod
    def backup_dir() -> Path:
        return paths.data_dir() / "backups"

    def maybe_backup(self, job: Job | None = None, force: bool = False) -> Path | None:
        """Index sichern (höchstens alle BACKUP_EVERY_HOURS Stunden), die BACKUPS_KEPT neuesten bleiben."""
        if not force and not self.engine.settings.indexing.backup_after_run:
            return None
        folder = self.backup_dir()
        existing = sorted(folder.glob("index-*.sqlite3")) if folder.exists() else []
        if not force and existing and time.time() - existing[-1].stat().st_mtime < BACKUP_EVERY_HOURS * 3600:
            return None
        if job:
            job.update(phase="Sicherung", message="Index wird gesichert …")
        dest = folder / f"index-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        try:
            self.store.backup(dest)
        except Exception as e:  # noqa: BLE001 - eine fehlgeschlagene Sicherung darf den Lauf nicht verderben
            log.warning("Sicherung fehlgeschlagen: %s", e)
            if job:
                job.note(f"Sicherung fehlgeschlagen: {e}")
            return None
        for old in sorted(folder.glob("index-*.sqlite3"))[:-BACKUPS_KEPT]:
            old.unlink(missing_ok=True)
        if job:
            job.note(f"Index gesichert: {dest.name}")
            job.update(phase="Fertig")
        return dest

    def check_disk_space(self, pending: int) -> None:
        folder = self.store.path.parent
        free = shutil.disk_usage(folder).free
        need = int((300 + pending * MB_PER_DOCUMENT) * 1024 * 1024)
        if free < need:
            raise RuntimeError(f"Zu wenig Speicherplatz auf dem Laufwerk von {folder}: frei {free / 2**30:.1f} GB, "
                               f"benötigt etwa {need / 2**30:.1f} GB für {pending} Texte (inkl. Sicherung).")

    def _run(self, job: Job, *, sync, collections, items, retry_errors, full_sync=False, corpus_id=None,
             deadline=None, max_docs=0, worker=None, processed: list | None = None, embed_only=False) -> dict:
        processed = processed if processed is not None else []
        settings = self.engine.settings
        result: dict = {"synced": None, "extracted": 0, "no_text": 0, "errors": 0, "embedded": 0}
        progress = job.counters
        progress.update(docs_total=0, docs_done=0, chunks_embedded=0, embed_rate=0.0, current=None,
                        recent=[], queue=[], eta=None)

        sources = self.sources_for(corpus_id, collections)
        libraries = self.engine.libraries_of(sources + list(items or []))
        if sync and libraries:
            job.update(phase="Abgleich mit Zotero", message="Einträge werden abgeglichen …")
            try:
                result["synced"] = self.sync_metadata(job, full=full_sync, libraries=libraries)
                job.note(f"Abgleich: {result['synced']}")
            except ZoteroUnavailable as e:
                job.note(f"Kein Abgleich: {e}")
                result["sync_error"] = str(e)

        raw_scope = self.scope(extra_items=items, collections=collections, corpus_id=corpus_id, resolve=False)
        # Dubletten, über die vor dem Lauf niemand entschieden hat (Hintergrund, Zotero-Plugin): Regel übernehmen
        progress["duplicates_auto"] = duplicates.acknowledge(self.store, raw_scope)
        if progress["duplicates_auto"]:
            job.note(f"{progress['duplicates_auto']} Werke liegen doppelt vor – Kopie nach der Regel gewählt")
        scope = self.engine.resolve_copies(raw_scope)
        if not scope:
            msg = ("Nichts zu indexieren: Lege unter „Wissenskorpora“ einen Korpus an und wähle Sammlungen "
                   "oder ganze Bibliotheken aus." if not sources and not items else
                   "Die gewählten Sammlungen enthalten (noch) keine Einträge – ist Zotero geöffnet?")
            job.note(msg)
            job.update(phase="Fertig", message=msg)
            result["nothing_selected"] = True
            return result
        if retry_errors:
            self.store.reset_attachments(scope)

        # Embedding-Modell früh prüfen – klare Meldung statt Abbruch mitten im Lauf
        job.update(phase="Vorbereitung", message="Embedding-Modell wird geladen …")
        space = self.engine.space()
        progress["space"] = space
        self.sync_abstracts(scope)
        self.reconcile_snapshots()

        pending = [] if embed_only else self.store.pending_attachments(scope, settings.indexing.content_types)
        if pending:
            self.check_disk_space(len(pending))
        # Gelesene Texte, deren Abschnitte für das aktive Modell fehlen (z. B. nach einem Modellwechsel): nicht neu
        # lesen, nur einbetten – und nur im gewählten Bereich (ein Korpus bettet nur seine eigenen Texte ein)
        pending_keys = {(a["lib"], a["key"]) for a in pending}
        to_embed = [a for a in self.store.attachments_to_embed(space, scope) if (a["lib"], a["key"]) not in pending_keys]
        work: list[tuple[str, dict]] = [("read", a) for a in pending] + [("embed", a) for a in to_embed]
        if max_docs and len(work) > max_docs:
            job.note(f"Etappe: {max_docs} von {len(work)} Texten in diesem Lauf")
            result["stopped"] = (f"Etappe beendet: {max_docs} Texte verarbeitet, {len(work) - max_docs} folgen "
                                 "im nächsten Lauf")
            work = work[:max_docs]
        items_meta = self.store.items((a["lib"], a["parent"]) for _, a in work)
        model = self.engine.embedding_label()
        n_read = sum(1 for kind, _ in work if kind == "read")
        n_embed = len(work) - n_read

        def title_of(att):
            it = items_meta.get((att["lib"], att["parent"])) or {}
            return it.get("title") or att.get("title") or att["key"], author_year(it) if it else ""

        progress.update(docs_total=len(work), model=model, to_read=n_read, to_embed=n_embed, fraction=0.0)
        if embed_only or (n_embed and not n_read):  # reiner Einbett-Lauf: so benennen
            name = (self.store.corpus(corpus_id) or {}).get("name") if corpus_id else None
            job.update(title=f"Einbetten für {model}: {name}" if name else f"Einbetten für {model}: alle Korpora")
        job.update(phase="Indexierung" if n_read else "Einbetten", total=len(work), done=0,
                   message=f"{len(work)} Dokumente zu verarbeiten" if work else "Alle Dokumente sind aktuell")
        job.note(f"{n_read} Texte zu lesen, {n_embed} Texte nur für {model} einzubetten")

        batch = settings.embedding.batch_size
        throttle = settings.indexing.throttle_seconds
        read_seconds: list[float] = []  # Dauer je gelesenem Text (lesen und einbetten)
        clock = {"embed_s": 0.0, "abstracts_left": len(self.store.abstracts_to_embed(space, scope))}

        def update_eta(next_index: int, cur: dict | None) -> None:
            """Restzeit aus der Einbett-Rate dieses Laufs: laufender Text, übrige Texte, Abstracts."""
            rate = progress["chunks_embedded"] / clock["embed_s"] if clock["embed_s"] > 0 else 0
            if rate:
                progress["embed_rate"] = round(rate, 2)
            rest = work[next_index:]
            reads_left = sum(1 for kind, _ in rest if kind == "read")
            chunks_left = sum(a["missing"] for kind, a in rest if kind == "embed") + clock["abstracts_left"]
            eta, known = 0.0, True
            cur_left = None
            if cur is not None:
                if cur["chunks_total"] and rate:
                    cur_left = (cur["chunks_total"] - cur["chunks_done"]) / rate
                    eta += cur_left
                elif cur.get("index"):
                    known = False  # Text wird noch gelesen
                cur["eta"] = round(cur_left) if cur_left is not None else None
            if reads_left:
                if read_seconds:
                    eta += reads_left * sum(read_seconds) / len(read_seconds)
                else:
                    known = False
            if chunks_left:
                if rate:
                    eta += chunks_left / rate
                else:
                    known = False
            progress["eta"] = round(eta) if (eta or known) else None
            progress["eta_partial"] = not known
            frac_cur = cur["chunks_done"] / cur["chunks_total"] if cur and cur["chunks_total"] and cur.get("index") else 0
            progress["fraction"] = round(min(1.0, (progress["docs_done"] + frac_cur) / len(work)), 4) if work else None

        def embed_document(att: dict, cur: dict, next_index: int) -> None:
            total = self.store.count_document_chunks_to_embed(space, att["lib"], att["key"], att["parent"])
            cur.update(step="Abschnitte werden eingebettet", chunks_total=total)
            update_eta(next_index, cur)
            while True:
                job.check()
                rows = self.store.document_chunks_to_embed(space, att["lib"], att["key"], att["parent"], batch)
                if not rows:
                    break
                t = time.time()
                n = self._embed_rows(rows, job, space)
                clock["embed_s"] += time.time() - t
                cur["chunks_done"] += n
                cur["percent"] = round(100 * cur["chunks_done"] / max(total, 1))
                progress["chunks_embedded"] += n
                result["embedded"] += n
                update_eta(next_index, cur)

        switched = False
        for i, (kind, att) in enumerate(work):
            job.check()
            if deadline and time.time() >= deadline:
                msg = f"Zeitfenster beendet nach {i} Texten – Fortsetzung im nächsten Zeitfenster"
                job.note(msg)
                result["stopped"] = msg
                progress["docs_total"] = i
                break
            title, citation = title_of(att)
            progress["queue"] = [title_of(a)[0] for _, a in work[i + 1: i + 6]]
            cur = {"title": title, "citation": citation, "pages": att.get("n_pages") if kind == "embed" else None,
                   "step": "Text wird gelesen" if kind == "read" else "Abschnitte werden eingebettet",
                   "chunks_total": 0, "chunks_done": 0, "percent": 0, "index": i + 1, "kind": kind,
                   "lib": att["lib"], "att_key": att["key"], "eta": None}
            progress["current"] = cur
            self.store.busy = (att["lib"], att["key"]) if kind == "read" else None
            job.update(message=title[:160])
            update_eta(i + 1, cur)
            t0 = time.time()
            try:
                if kind == "embed":
                    status, msg = "embedded", ""
                    embed_document(att, cur, i + 1)
                    row = att
                else:
                    try:
                        status, msg = self.extract_one(att, worker=worker, check=job.check)
                    except Exception as e:  # noqa: BLE001
                        if type(e).__name__ == "JobCancelled":
                            raise
                        status, msg = "error", str(e)
                        self.store.set_attachment_status(
                            att["lib"], att["key"], "error", error=str(e), indexed_md5=att.get("md5"),
                            indexed_at=time.time(), **file_stat(Path(att["path"]) if att.get("path") else None))
                    row = self.store.attachment(att["lib"], att["key"]) or {}
                    cur["pages"] = row.get("n_pages")
                    if status == "indexed":
                        result["extracted"] += 1
                        embed_document(att, cur, i + 1)
                        read_seconds.append(time.time() - t0)
                    elif status == "no_text":
                        result["no_text"] += 1
                    else:
                        result["errors"] += 1
                        job.note(f"Fehler bei „{title[:60]}“: {msg}")
            except EmbeddingSwitched:
                # Gelesener Text bleibt gespeichert (für das neue Modell „einzubetten“); hier sauber aufhören
                switched = True
                self.store.busy = None
                break

            cur.update(step="fertig", percent=100)
            entry = {"title": title, "citation": citation, "status": status, "message": msg or "",
                     "pages": row.get("n_pages"), "chunks": cur["chunks_total"], "seconds": round(time.time() - t0, 1)}
            progress["recent"] = ([entry] + progress["recent"])[:8]
            processed.append({**entry, "lib": att["lib"], "parent": att["parent"], "key": att["key"]})
            progress["docs_done"] = i + 1
            self.store.busy = None
            update_eta(i + 1, None)
            job.step()
            if throttle:
                job.sleep(throttle)

        # PDFs ohne Text: deren Schnappschüsse kommen im nächsten Lauf an die Reihe
        self.reconcile_snapshots()

        # Abstracts von Einträgen ohne Volltext (nur im gewählten Bereich)
        rest = [] if switched else self.store.abstracts_to_embed(space, scope)
        if rest and not (deadline and time.time() >= deadline):
            cur = {"title": "Abstracts von Einträgen ohne Volltext", "citation": "", "step": "Abschnitte werden eingebettet",
                   "pages": None, "chunks_total": len(rest), "chunks_done": 0, "percent": 0, "index": None, "eta": None}
            progress["current"] = cur
            progress["queue"] = []
            job.update(phase="Abschluss", message=f"{len(rest)} Abstracts")
            for b in range(0, len(rest), batch):
                job.check()
                t = time.time()
                try:
                    n = self._embed_rows(rest[b: b + batch], job, space)
                except EmbeddingSwitched:
                    switched = True
                    break
                clock["embed_s"] += time.time() - t
                cur["chunks_done"] += n
                cur["percent"] = round(100 * cur["chunks_done"] / max(len(rest), 1))
                progress["chunks_embedded"] += n
                result["embedded"] += n
                clock["abstracts_left"] = len(rest) - cur["chunks_done"]
                update_eta(len(work), cur)
                if not work:
                    progress["fraction"] = round(cur["chunks_done"] / len(rest), 4)
        if switched:
            job.note(MODEL_SWITCHED)
            result.update(stopped=MODEL_SWITCHED, switched=True)
        result["embedded_docs"] = sum(1 for d in processed if d["status"] == "embedded")
        progress["current"] = None
        progress["eta"] = 0
        progress["fraction"] = 1.0
        job.check()
        job.update(phase="Fertig", message=result.get("stopped") or "Index ist aktuell")
        return result
