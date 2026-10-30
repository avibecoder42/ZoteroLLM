"""SQLite-Ablage ``research.db`` (Datenmodell aus dem Konzept, Abschnitt 3.4).

Eine eigene Datei, die ZotLLM unverändert übernehmen kann. Eine Verbindung für alle Threads, geschützt durch eine
Sperre (FastAPI ruft synchrone Endpunkte aus einem Thread-Pool auf).

- query: Suchstrings, versioniert (jede Änderung eine neue Zeile mit version+1, die alte wird inaktiv)
- run: jede Ausführung (Suche oder Import) mit Datum, String, Limits und Trefferzahl
- record: der Pool je Projekt, ohne Duplikate (record_key hält DOI, PMID, OpenAlex-ID, AN und Titel)
- hit: welcher Lauf welchen Datensatz gefunden hat
- decision: Screening-Entscheide als Verlauf – gültig ist der jüngste je Datensatz. Das Kennzeichen „Grenzfall“
  (borderline) gehört zum Entscheid und wird von einem Entscheid zum nächsten mitgenommen.
- rule_review: Ausgeblendete, die von Hand geprüft wurden (zurückgeholt, Grenzfall, Ausschluss bestätigt)
- ai_suggestion: KI-Vorschlag je Datensatz (passend / nicht passend / Grenzfall), getrennt vom Entscheid; beim
  Entscheid wird der damalige Vorschlag in decision.ai_suggestion/ai_reason festgehalten

Schema-Version 2 (Phase 2a): decision.borderline/borderline_reason und rule_review; Version 3 (Phase 2b):
ai_suggestion. Ältere Dateien werden beim Öffnen ergänzt.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .errors import NotFound
from .records import dedup_keys, merge, normalize, years_conflict

SCHEMA_VERSION = 4
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS project(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, question TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
  criteria_in TEXT NOT NULL DEFAULT '', criteria_out TEXT NOT NULL DEFAULT '',
  target_library TEXT NOT NULL DEFAULT 'users/0', target_name TEXT NOT NULL DEFAULT '',
  zotero_backend TEXT NOT NULL DEFAULT 'web', folder_map TEXT NOT NULL DEFAULT '[]',
  prefilters TEXT NOT NULL DEFAULT '[]', settings TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS block(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'include',
  field TEXT NOT NULL DEFAULT 'tiab', terms TEXT NOT NULL DEFAULT '[]', mesh TEXT NOT NULL DEFAULT '[]',
  psycinfo TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS query(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  name TEXT NOT NULL, source TEXT NOT NULL, string TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
  limits TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, last_count INTEGER, counted_at TEXT, translation TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS run(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  query_id INTEGER, kind TEXT NOT NULL DEFAULT 'search', source TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
  string TEXT NOT NULL DEFAULT '', version INTEGER, limits TEXT NOT NULL DEFAULT '{}', run_at TEXT NOT NULL,
  hits INTEGER, fetched INTEGER NOT NULL DEFAULT 0, new_records INTEGER NOT NULL DEFAULT 0,
  duplicates INTEGER NOT NULL DEFAULT 0, translation TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS record(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  doi TEXT NOT NULL DEFAULT '', pmid TEXT NOT NULL DEFAULT '', openalex_id TEXT NOT NULL DEFAULT '',
  ovid_an TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', authors TEXT NOT NULL DEFAULT '[]', year INTEGER,
  journal TEXT NOT NULL DEFAULT '', abstract TEXT NOT NULL DEFAULT '', lang TEXT NOT NULL DEFAULT '',
  subjects TEXT NOT NULL DEFAULT '[]', type TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, zotero_key TEXT NOT NULL DEFAULT '', zotero_lib TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS record_project ON record(project_id);
CREATE TABLE IF NOT EXISTS record_key(
  project_id INTEGER NOT NULL, key TEXT NOT NULL, record_id INTEGER NOT NULL REFERENCES record(id) ON DELETE CASCADE,
  PRIMARY KEY(project_id, key));
CREATE TABLE IF NOT EXISTS hit(
  run_id INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
  record_id INTEGER NOT NULL REFERENCES record(id) ON DELETE CASCADE, rank INTEGER, PRIMARY KEY(run_id, record_id));
CREATE INDEX IF NOT EXISTS hit_record ON hit(record_id);
CREATE TABLE IF NOT EXISTS decision(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  record_id INTEGER NOT NULL REFERENCES record(id) ON DELETE CASCADE, status TEXT NOT NULL, folder INTEGER,
  reason TEXT NOT NULL DEFAULT '', by TEXT NOT NULL DEFAULT '', ai_suggestion TEXT, ai_reason TEXT, at TEXT NOT NULL,
  borderline INTEGER NOT NULL DEFAULT 0, borderline_reason TEXT NOT NULL DEFAULT '',
  ai_shown INTEGER, method TEXT NOT NULL DEFAULT 'card', batch TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS decision_record ON decision(project_id, record_id);
CREATE TABLE IF NOT EXISTS rule_review(
  project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  record_id INTEGER NOT NULL REFERENCES record(id) ON DELETE CASCADE, rule_id TEXT NOT NULL, verdict TEXT NOT NULL,
  by TEXT NOT NULL DEFAULT '', at TEXT NOT NULL, PRIMARY KEY(project_id, record_id, rule_id));
CREATE TABLE IF NOT EXISTS ai_suggestion(
  project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  record_id INTEGER NOT NULL REFERENCES record(id) ON DELETE CASCADE, label TEXT NOT NULL DEFAULT '',
  folder INTEGER, reason TEXT NOT NULL DEFAULT '', criterion TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL, PRIMARY KEY(project_id, record_id));
CREATE TABLE IF NOT EXISTS zotero_link(
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  record_id INTEGER NOT NULL REFERENCES record(id) ON DELETE CASCADE, library TEXT NOT NULL, item_key TEXT NOT NULL,
  collection TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '', at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS zotero_index(
  project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE, library TEXT NOT NULL, key TEXT NOT NULL,
  item_key TEXT NOT NULL, PRIMARY KEY(project_id, library, key));
CREATE TABLE IF NOT EXISTS log(
  id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES project(id) ON DELETE CASCADE, at TEXT NOT NULL,
  kind TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}');
"""

PROJECT_JSON = ("folder_map", "prefilters", "settings")
PROJECT_FIELDS = ("title", "question", "description", "criteria_in", "criteria_out", "target_library", "target_name",
                  "zotero_backend", *PROJECT_JSON)
BLOCK_JSON = ("terms", "mesh", "psycinfo")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _row(r: sqlite3.Row | None, json_fields=()) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in json_fields:
        if k in d and isinstance(d[k], str):
            d[k] = json.loads(d[k] or "null")
    return d


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode = WAL")
            self._db.executescript(SCHEMA)
            self._migrate()
            self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))

    def _migrate(self) -> None:
        cols = {r["name"] for r in self._db.execute("PRAGMA table_info(decision)")}
        if "borderline" not in cols:
            self._db.execute("ALTER TABLE decision ADD COLUMN borderline INTEGER NOT NULL DEFAULT 0")
        if "borderline_reason" not in cols:
            self._db.execute("ALTER TABLE decision ADD COLUMN borderline_reason TEXT NOT NULL DEFAULT ''")
        # v4: War der KI-Vorschlag beim Entscheid sichtbar? Karte oder Liste? Stapel einer Sammel-Übernahme
        if "ai_shown" not in cols:
            self._db.execute("ALTER TABLE decision ADD COLUMN ai_shown INTEGER")
        if "method" not in cols:
            self._db.execute("ALTER TABLE decision ADD COLUMN method TEXT NOT NULL DEFAULT 'card'")
        if "batch" not in cols:
            self._db.execute("ALTER TABLE decision ADD COLUMN batch TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def tx(self):
        with self._lock:
            self._db.execute("BEGIN")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    # ------------------------------------------------------------------------------------------ Projekte
    def projects(self) -> list[dict]:
        return [_row(r, PROJECT_JSON) for r in self.q("SELECT * FROM project ORDER BY updated_at DESC, id DESC")]

    def project(self, pid: int) -> dict:
        p = _row(self.one("SELECT * FROM project WHERE id = ?", (pid,)), PROJECT_JSON)
        if not p:
            raise NotFound(f"Projekt {pid} gibt es nicht.")
        return p

    def create_project(self, data: dict) -> dict:
        fields = {k: data[k] for k in PROJECT_FIELDS if k in data and data[k] is not None}
        fields.setdefault("title", "Neues Projekt")
        for k in PROJECT_JSON:
            if k in fields:
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        stamp = now()
        cols = list(fields) + ["created_at", "updated_at"]
        with self.tx() as db:
            cur = db.execute(f"INSERT INTO project({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                             [*fields.values(), stamp, stamp])
            pid = cur.lastrowid
        return self.project(pid)

    def update_project(self, pid: int, data: dict) -> dict:
        self.project(pid)
        fields = {k: data[k] for k in PROJECT_FIELDS if k in data and data[k] is not None}
        for k in PROJECT_JSON:
            if k in fields:
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            with self.tx() as db:
                db.execute(f"UPDATE project SET {sets}, updated_at = ? WHERE id = ?", [*fields.values(), now(), pid])
        return self.project(pid)

    def touch(self, pid: int) -> None:
        with self.tx() as db:
            db.execute("UPDATE project SET updated_at = ? WHERE id = ?", (now(), pid))

    def delete_project(self, pid: int) -> None:
        self.project(pid)
        with self.tx() as db:
            db.execute("DELETE FROM record_key WHERE project_id = ?", (pid,))
            db.execute("DELETE FROM project WHERE id = ?", (pid,))

    # ------------------------------------------------------------------------------------------ Blöcke
    def blocks(self, pid: int) -> list[dict]:
        return [_row(r, BLOCK_JSON) for r in self.q("SELECT * FROM block WHERE project_id = ? ORDER BY position, id", (pid,))]

    def replace_blocks(self, pid: int, blocks: list[dict]) -> list[dict]:
        self.project(pid)
        with self.tx() as db:
            db.execute("DELETE FROM block WHERE project_id = ?", (pid,))
            for i, b in enumerate(blocks):
                db.execute("INSERT INTO block(project_id, position, name, kind, field, terms, mesh, psycinfo, note) "
                           "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (pid, i, b.get("name", ""), b.get("kind") or "include", b.get("field") or "tiab",
                            *(json.dumps(b.get(k) or [], ensure_ascii=False) for k in BLOCK_JSON), b.get("note", "")))
            db.execute("UPDATE project SET updated_at = ? WHERE id = ?", (now(), pid))
        return self.blocks(pid)

    # ------------------------------------------------------------------------------------------ Suchstrings
    def queries(self, pid: int, include_old: bool = False) -> list[dict]:
        sql = "SELECT * FROM query WHERE project_id = ?" + ("" if include_old else " AND active = 1")
        return [_row(r, ("limits",)) for r in self.q(sql + " ORDER BY source, name, version", (pid,))]

    def query(self, qid: int) -> dict:
        r = _row(self.one("SELECT * FROM query WHERE id = ?", (qid,)), ("limits",))
        if not r:
            raise NotFound(f"Suchstring {qid} gibt es nicht.")
        return r

    def query_versions(self, qid: int) -> list[dict]:
        q = self.query(qid)
        return [_row(r, ("limits",)) for r in self.q(
            "SELECT * FROM query WHERE project_id = ? AND name = ? AND source = ? ORDER BY version DESC",
            (q["project_id"], q["name"], q["source"]))]

    def add_query(self, pid: int, name: str, source: str, string: str, limits: dict | None = None,
                  note: str = "") -> dict:
        """Neuer Suchstring – gibt es den Namen für die Quelle schon, wird es eine neue Version."""
        self.project(pid)
        with self.tx() as db:
            prev = db.execute("SELECT MAX(version) FROM query WHERE project_id = ? AND name = ? AND source = ?",
                              (pid, name, source)).fetchone()[0]
            db.execute("UPDATE query SET active = 0 WHERE project_id = ? AND name = ? AND source = ?", (pid, name, source))
            cur = db.execute("INSERT INTO query(project_id, name, source, string, version, limits, note, created_at) "
                             "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                             (pid, name, source, string, (prev or 0) + 1, json.dumps(limits or {}), note, now()))
            qid = cur.lastrowid
            db.execute("UPDATE project SET updated_at = ? WHERE id = ?", (now(), pid))
        return self.query(qid)

    def update_query(self, qid: int, *, string: str | None = None, limits: dict | None = None,
                     name: str | None = None, note: str | None = None) -> dict:
        """Geänderter String → neue Version; nur Limits/Notiz → an Ort und Stelle (auch Name, solange nie gesucht)."""
        q = self.query(qid)
        if string is not None and string.strip() != q["string"].strip():
            return self.add_query(q["project_id"], name or q["name"], q["source"], string.strip(),
                                  limits if limits is not None else q["limits"], note if note is not None else q["note"])
        with self.tx() as db:
            if limits is not None:
                db.execute("UPDATE query SET limits = ?, last_count = NULL, counted_at = NULL WHERE id = ?",
                           (json.dumps(limits), qid))
            if note is not None:
                db.execute("UPDATE query SET note = ? WHERE id = ?", (note, qid))
            if name and name != q["name"]:
                db.execute("UPDATE query SET name = ? WHERE project_id = ? AND name = ? AND source = ?",
                           (name, q["project_id"], q["name"], q["source"]))
        return self.query(qid)

    def set_count(self, qid: int, count: int, translation: str = "") -> dict:
        with self.tx() as db:
            db.execute("UPDATE query SET last_count = ?, counted_at = ?, translation = ? WHERE id = ?",
                       (count, now(), translation, qid))
        return self.query(qid)

    def delete_query(self, qid: int) -> None:
        q = self.query(qid)
        with self.tx() as db:  # alle Versionen; Läufe bleiben im Protokoll (mit String und Version)
            db.execute("DELETE FROM query WHERE project_id = ? AND name = ? AND source = ?", (q["project_id"], q["name"], q["source"]))

    # ------------------------------------------------------------------------------------------ Läufe und Pool
    def add_run(self, pid: int, **fields) -> int:
        fields = dict(fields)
        if "limits" in fields:
            fields["limits"] = json.dumps(fields["limits"] or {})
        fields.setdefault("run_at", now())
        cols = ["project_id", *fields]
        with self.tx() as db:
            cur = db.execute(f"INSERT INTO run({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", [pid, *fields.values()])
            return cur.lastrowid

    def update_run(self, run_id: int, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as db:
            db.execute(f"UPDATE run SET {sets} WHERE id = ?", [*fields.values(), run_id])

    def runs(self, pid: int) -> list[dict]:
        return [_row(r, ("limits",)) for r in self.q("SELECT * FROM run WHERE project_id = ? ORDER BY run_at, id", (pid,))]

    def add_records(self, pid: int, run_id: int, records: list[dict]) -> dict:
        """Datensätze in den Pool: neue anlegen, Duplikate zusammenführen (fehlende Felder ergänzen).
        Rückgabe: Zahlen für Lauf und Protokoll."""
        new = dup_pool = dup_internal = 0
        seen_in_run: set[int] = set()
        with self.tx() as db:
            for rank, raw in enumerate(records):
                rec = normalize(raw)
                keys = dedup_keys(rec)  # leer: ohne DOI und mit sehr kurzem Titel – kommt ohne Abgleich in den Pool
                match = None
                rows = db.execute(f"SELECT key, record_id FROM record_key WHERE project_id = ? AND key IN "
                                  f"({', '.join('?' * len(keys))})", (pid, *keys)).fetchall() if keys else []
                strong = [r["record_id"] for r in rows if not r["key"].startswith("title:")]
                weak = [r["record_id"] for r in rows if r["key"].startswith("title:")]
                if strong:
                    match = strong[0]
                elif weak:
                    other = json.loads(db.execute("SELECT data FROM record WHERE id = ?", (weak[0],)).fetchone()[0])
                    if not years_conflict(rec, other) and not _ids_conflict(rec, other):
                        match = weak[0]
                if match is None:
                    cur = db.execute("INSERT INTO record(project_id, created_at) VALUES(?, ?)", (pid, now()))
                    rid = cur.lastrowid
                    self._write_record(db, rid, rec)
                    new += 1
                else:
                    rid = match
                    old = json.loads(db.execute("SELECT data FROM record WHERE id = ?", (rid,)).fetchone()[0])
                    merged = merge(old, rec)
                    if merged != old:
                        self._write_record(db, rid, merged)
                    if rid in seen_in_run:
                        dup_internal += 1
                    else:
                        dup_pool += 1
                    keys = dedup_keys(merged)
                for k in keys:
                    db.execute("INSERT OR IGNORE INTO record_key(project_id, key, record_id) VALUES(?, ?, ?)", (pid, k, rid))
                db.execute("INSERT OR IGNORE INTO hit(run_id, record_id, rank) VALUES(?, ?, ?)", (run_id, rid, rank))
                seen_in_run.add(rid)
            db.execute("UPDATE project SET updated_at = ? WHERE id = ?", (now(), pid))
        return {"fetched": len(records), "new": new, "duplicates": dup_pool, "duplicates_in_run": dup_internal}

    @staticmethod
    def _write_record(db, rid: int, rec: dict) -> None:
        db.execute("UPDATE record SET doi = ?, pmid = ?, openalex_id = ?, ovid_an = ?, title = ?, authors = ?, year = ?, "
                   "journal = ?, abstract = ?, lang = ?, subjects = ?, type = ?, data = ? WHERE id = ?",
                   (rec.get("doi", ""), rec.get("pmid", ""), rec.get("openalex_id", ""), rec.get("accession", ""),
                    rec.get("title", ""), json.dumps(rec.get("authors") or [], ensure_ascii=False), rec.get("year"),
                    rec.get("container", ""), rec.get("abstract", ""), rec.get("lang", ""),
                    json.dumps(rec.get("subjects") or [], ensure_ascii=False), rec.get("type", ""),
                    json.dumps(rec, ensure_ascii=False), rid))

    def update_record_data(self, rid: int, rec: dict) -> None:
        with self.tx() as db:
            self._write_record(db, rid, rec)

    # Aktuelle Läufe: je Suchstring und Quelle die letzte Suche (der Suchstring muss noch bestehen), dazu alle Importe
    CURRENT_RUNS = """SELECT r.id FROM run r WHERE r.project_id = ? AND (r.kind != 'search' OR (
      r.id = (SELECT MAX(r2.id) FROM run r2 WHERE r2.project_id = r.project_id AND r2.kind = 'search'
              AND r2.source = r.source AND r2.name = r.name)
      AND EXISTS (SELECT 1 FROM query q WHERE q.project_id = r.project_id AND q.source = r.source AND q.name = r.name)))"""

    def current_runs(self, pid: int) -> set[int]:
        return {r[0] for r in self.q(self.CURRENT_RUNS, (pid,))}

    def delete_records(self, pid: int) -> int:
        """Pool leeren: alle Datensätze samt Fundstellen, Entscheiden und KI-Vorschlägen. Suchstrings und das
        Protokoll der Läufe bleiben."""
        with self.tx() as db:
            n = db.execute("DELETE FROM record WHERE project_id = ?", (pid,)).rowcount
            db.execute("UPDATE run SET new_records = 0 WHERE project_id = ?", (pid,))
        return n

    def records(self, pid: int) -> list[dict]:
        """Alle Datensätze mit Fundstellen (Quelle, Suchstring; ``current``: aus einem aktuellen Lauf) und Entscheid."""
        rows = self.q("SELECT id, doi, pmid, openalex_id, ovid_an, title, authors, year, journal, abstract, lang, "
                      "subjects, type, data, zotero_key, zotero_lib, created_at FROM record WHERE project_id = ? ORDER BY id", (pid,))
        found: dict[int, list[dict]] = {}
        current = self.current_runs(pid)
        for h in self.q("SELECT hit.record_id, hit.rank, run.id AS run_id, run.source, run.name, run.kind FROM hit "
                        "JOIN run ON run.id = hit.run_id WHERE run.project_id = ? ORDER BY run.id", (pid,)):
            found.setdefault(h["record_id"], []).append(
                {"run": h["run_id"], "source": h["source"], "query": h["name"], "rank": h["rank"],
                 "current": h["run_id"] in current})
        decisions = self.current_decisions(pid)
        ai = self.ai_suggestions(pid)
        out = []
        for r in rows:
            d = _row(r, ("authors", "subjects", "data"))
            d["found"] = found.get(d["id"], [])
            d["current"] = not d["found"] or any(f["current"] for f in d["found"])
            d["decision"] = decisions.get(d["id"])
            d["ai"] = ai.get(d["id"])
            out.append(d)
        return out

    def record(self, pid: int, rid: int) -> dict:
        r = _row(self.one("SELECT * FROM record WHERE id = ? AND project_id = ?", (rid, pid)), ("authors", "subjects", "data"))
        if not r:
            raise NotFound(f"Datensatz {rid} gibt es in diesem Projekt nicht.")
        return r

    # ------------------------------------------------------------------------------------------ Entscheide
    def add_decision(self, pid: int, rid: int, status: str, folder: int | None = None, reason: str = "",
                     by: str = "", ai_suggestion: str | None = None, ai_reason: str | None = None,
                     borderline: bool = False, borderline_reason: str = "", ai_shown: bool | None = None,
                     method: str = "card", batch: str = "") -> dict:
        return self.add_decisions(pid, [dict(record_id=rid, status=status, folder=folder, reason=reason, by=by,
                                             ai_suggestion=ai_suggestion, ai_reason=ai_reason, borderline=borderline,
                                             borderline_reason=borderline_reason, ai_shown=ai_shown, method=method,
                                             batch=batch)])[0]

    def add_decisions(self, pid: int, rows: list[dict]) -> list[dict]:
        """Mehrere Entscheide in einer Transaktion (Sammel-Übernahme aus der Liste)."""
        for r in rows:
            self.record(pid, r["record_id"])
        stamp, ids = now(), []
        with self.tx() as db:
            for r in rows:
                shown = r.get("ai_shown")
                cur = db.execute("INSERT INTO decision(project_id, record_id, status, folder, reason, by, ai_suggestion, "
                                 "ai_reason, at, borderline, borderline_reason, ai_shown, method, batch) "
                                 "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (pid, r["record_id"], r["status"], r.get("folder"), r.get("reason") or "", r.get("by") or "",
                                  r.get("ai_suggestion"), r.get("ai_reason"), stamp, 1 if r.get("borderline") else 0,
                                  r.get("borderline_reason") or "", None if shown is None else int(bool(shown)),
                                  r.get("method") or "card", r.get("batch") or ""))
                ids.append(cur.lastrowid)
            db.execute("UPDATE project SET updated_at = ? WHERE id = ?", (stamp, pid))
        marks = ",".join("?" * len(ids))
        by_id = {r["id"]: _row(r) for r in self.q(f"SELECT * FROM decision WHERE id IN ({marks})", tuple(ids))} if ids else {}
        return [by_id[i] for i in ids]

    def current_decisions(self, pid: int) -> dict[int, dict]:
        rows = self.q("SELECT d.* FROM decision d JOIN (SELECT record_id, MAX(id) AS mid FROM decision "
                      "WHERE project_id = ? GROUP BY record_id) last ON last.mid = d.id", (pid,))
        return {r["record_id"]: dict(r) for r in rows if r["status"] != "open" or r["borderline"]}

    def current_decision(self, pid: int, rid: int) -> dict | None:
        r = self.one("SELECT * FROM decision WHERE project_id = ? AND record_id = ? ORDER BY id DESC LIMIT 1", (pid, rid))
        return dict(r) if r else None

    def undo_decision(self, pid: int) -> dict | None:
        """Den jüngsten Entscheid im Projekt zurücknehmen; der vorherige zum selben Datensatz gilt wieder. Gehört er zu
        einer Sammel-Übernahme, wird sie als Ganzes zurückgenommen."""
        last = self.one("SELECT * FROM decision WHERE project_id = ? ORDER BY id DESC LIMIT 1", (pid,))
        if not last:
            return None
        with self.tx() as db:
            if last["batch"]:
                n = db.execute("DELETE FROM decision WHERE project_id = ? AND batch = ?", (pid, last["batch"])).rowcount
            else:
                n = db.execute("DELETE FROM decision WHERE id = ?", (last["id"],)).rowcount
        return {**dict(last), "count": n}

    def decision_history(self, pid: int) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM decision WHERE project_id = ? ORDER BY id", (pid,))]

    # ------------------------------------------------------------------------------------------ Geprüfte Ausgeblendete
    def set_review(self, pid: int, rid: int, rule_id: str, verdict: str, by: str = "") -> None:
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO rule_review(project_id, record_id, rule_id, verdict, by, at) "
                       "VALUES(?, ?, ?, ?, ?, ?)", (pid, rid, rule_id, verdict, by or "", now()))

    def reviews(self, pid: int) -> dict[int, dict[str, str]]:
        out: dict[int, dict[str, str]] = {}
        for r in self.q("SELECT record_id, rule_id, verdict FROM rule_review WHERE project_id = ?", (pid,)):
            out.setdefault(r["record_id"], {})[r["rule_id"]] = r["verdict"]
        return out

    # ------------------------------------------------------------------------------------------ KI-Vorschläge
    def set_ai_suggestions(self, pid: int, rows: list[dict], model: str) -> None:
        stamp = now()
        with self.tx() as db:
            db.executemany("INSERT OR REPLACE INTO ai_suggestion(project_id, record_id, label, folder, reason, criterion, "
                           "model, at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                           [(pid, r["id"], r.get("label") or "", r.get("folder"), r.get("reason") or "",
                             r.get("criterion") or "", model, stamp) for r in rows])

    def ai_suggestions(self, pid: int) -> dict[int, dict]:
        return {r["record_id"]: {k: r[k] for k in ("label", "folder", "reason", "criterion", "model", "at")}
                for r in self.q("SELECT * FROM ai_suggestion WHERE project_id = ?", (pid,))}

    def clear_ai_suggestions(self, pid: int) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM ai_suggestion WHERE project_id = ?", (pid,))

    # ------------------------------------------------------------------------------------------ Zotero
    def replace_zotero_index(self, pid: int, library: str, index: dict[str, str]) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM zotero_index WHERE project_id = ? AND library = ?", (pid, library))
            db.executemany("INSERT INTO zotero_index(project_id, library, key, item_key) VALUES(?, ?, ?, ?)",
                           [(pid, library, k, v) for k, v in index.items()])

    def zotero_index(self, pid: int, library: str) -> dict[str, str]:
        return {r["key"]: r["item_key"] for r in self.q(
            "SELECT key, item_key FROM zotero_index WHERE project_id = ? AND library = ?", (pid, library))}

    def set_zotero_matches(self, pid: int, library: str, matches: dict[int, str]) -> None:
        with self.tx() as db:
            db.execute("UPDATE record SET zotero_key = '', zotero_lib = '' WHERE project_id = ? AND zotero_lib = ?", (pid, library))
            db.executemany("UPDATE record SET zotero_key = ?, zotero_lib = ? WHERE id = ? AND project_id = ?",
                           [(key, library, rid, pid) for rid, key in matches.items()])

    def add_link(self, pid: int, rid: int, library: str, item_key: str, collection: str, action: str) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO zotero_link(project_id, record_id, library, item_key, collection, action, at) "
                       "VALUES(?, ?, ?, ?, ?, ?, ?)", (pid, rid, library, item_key, collection, action, now()))
            db.execute("UPDATE record SET zotero_key = ?, zotero_lib = ? WHERE id = ?", (item_key, library, rid))

    def links(self, pid: int) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM zotero_link WHERE project_id = ? ORDER BY id", (pid,))]

    # ------------------------------------------------------------------------------------------ Protokoll
    def log(self, pid: int | None, kind: str, **detail) -> None:
        with self.tx() as db:
            db.execute("INSERT INTO log(project_id, at, kind, detail) VALUES(?, ?, ?, ?)",
                       (pid, now(), kind, json.dumps(detail, ensure_ascii=False)))

    def logs(self, pid: int) -> list[dict]:
        return [_row(r, ("detail",)) for r in self.q("SELECT * FROM log WHERE project_id = ? ORDER BY id", (pid,))]


def _ids_conflict(a: dict, b: dict) -> bool:
    """Gleicher Titel, aber verschiedene DOI bzw. PMID: verschiedene Arbeiten."""
    for k in ("doi", "pmid"):
        if a.get(k) and b.get(k) and str(a[k]).lower() != str(b[k]).lower():
            return True
    return False
