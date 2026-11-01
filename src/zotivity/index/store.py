"""SQLite-Index: Metadaten, Abschnitte, Volltextsuche (FTS5) und Vektoren.

Vektoren werden je "Embedding-Raum" (Anbieter + Modell + Dimension) abgelegt.
So können zwei Modelle parallel indexiert und verglichen werden; ein
Modellwechsel verwirft nichts, sondern legt einen neuen Raum an.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from zotivity.extract.chunker import Chunk

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS libraries(
    lib TEXT PRIMARY KEY, name TEXT, server_id TEXT,
    items_version INTEGER DEFAULT 0, collections_version INTEGER DEFAULT 0, synced_at REAL
);

CREATE TABLE IF NOT EXISTS collections(
    lib TEXT, key TEXT, name TEXT, parent TEXT, num_items INTEGER,
    PRIMARY KEY(lib, key)
);

CREATE TABLE IF NOT EXISTS items(
    lib TEXT, key TEXT, version INTEGER, item_type TEXT, title TEXT, creators TEXT,
    creator_summary TEXT, year INTEGER, date TEXT, publication TEXT, abstract TEXT,
    doi TEXT, url TEXT, tags TEXT, collections TEXT, language TEXT, updated_at REAL,
    PRIMARY KEY(lib, key)
);

CREATE TABLE IF NOT EXISTS attachments(
    lib TEXT, key TEXT, parent TEXT, version INTEGER, title TEXT, content_type TEXT,
    link_mode TEXT, path TEXT, md5 TEXT, mtime INTEGER,
    status TEXT DEFAULT 'pending', error TEXT, method TEXT,
    n_pages INTEGER, n_chars INTEGER, n_chunks INTEGER, indexed_md5 TEXT, indexed_at REAL,
    PRIMARY KEY(lib, key)
);
CREATE INDEX IF NOT EXISTS att_parent ON attachments(lib, parent);
CREATE INDEX IF NOT EXISTS att_status ON attachments(status);

CREATE TABLE IF NOT EXISTS spaces(
    space TEXT PRIMARY KEY, provider TEXT, model TEXT, dim INTEGER, params TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS embeddings(
    space TEXT, chunk_id INTEGER, vec BLOB, PRIMARY KEY(space, chunk_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS emb_chunk ON embeddings(chunk_id);

CREATE TABLE IF NOT EXISTS chunks(
    id INTEGER PRIMARY KEY, lib TEXT, item_key TEXT, att_key TEXT, ord INTEGER, kind TEXT,
    page_start INTEGER, page_end INTEGER, page_label TEXT, text TEXT
);
CREATE INDEX IF NOT EXISTS chunks_item ON chunks(lib, item_key);
CREATE INDEX IF NOT EXISTS chunks_att ON chunks(lib, att_key, ord);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize="unicode61 remove_diacritics 2"
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
    DELETE FROM embeddings WHERE chunk_id = old.id;
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE OF text ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
    DELETE FROM embeddings WHERE chunk_id = old.id;
END;

CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY, title TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS chat_messages(
    id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT, sources TEXT, meta TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS chat_msg_chat ON chat_messages(chat_id, id);

CREATE TABLE IF NOT EXISTS sheets(
    lib TEXT, item_key TEXT, sheet TEXT, model TEXT, note_key TEXT, created_at REAL,
    PRIMARY KEY(lib, item_key)
);

CREATE TABLE IF NOT EXISTS corpora(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT, sources TEXT, created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS reviews(
    id INTEGER PRIMARY KEY, title TEXT, question TEXT, state TEXT, created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS projects(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT, color TEXT,
    created_at REAL, updated_at REAL, opened_at REAL
);
CREATE TABLE IF NOT EXISTS project_corpora(
    project_id INTEGER, corpus_id INTEGER, PRIMARY KEY(project_id, corpus_id)
);
CREATE TABLE IF NOT EXISTS review_docs(
    review_id INTEGER, lib TEXT, item_key TEXT, score REAL, hits INTEGER, decision TEXT,
    reason TEXT, included INTEGER, PRIMARY KEY(review_id, lib, item_key)
);
CREATE TABLE IF NOT EXISTS searches(
    id INTEGER PRIMARY KEY, project_id INTEGER, signature TEXT, query TEXT, sort TEXT, total INTEGER,
    created_at REAL, used_at REAL, UNIQUE(project_id, signature)
);
CREATE TABLE IF NOT EXISTS review_pages(
    review_id INTEGER, ref TEXT, page INTEGER, PRIMARY KEY(review_id, ref)
);
-- In Zotero gelöschte Einträge: Kurzangaben, damit Belege in Forschungsständen und Antworten lesbar bleiben und auf
-- eine noch vorhandene Kopie desselben Werks umgestellt werden können (siehe references.py)
CREATE TABLE IF NOT EXISTS removed_items(
    lib TEXT, key TEXT, item_type TEXT, title TEXT, creators TEXT, creator_summary TEXT, year INTEGER, date TEXT,
    publication TEXT, doi TEXT, data TEXT, removed_at REAL, PRIMARY KEY(lib, key)
);
-- Dubletten (dasselbe Werk mehrfach in Zotero): Entscheidung je Werk – user (Kopie von Hand gewählt), rule (Regel),
-- separate (keine Dublette); siehe index/duplicates.py
CREATE TABLE IF NOT EXISTS duplicate_choices(
    work TEXT PRIMARY KEY, mode TEXT, lib TEXT, item_key TEXT, updated_at REAL
);
-- Verlauf der Indexierläufe (nur Läufe mit Arbeit, Fehler oder Abbruch; reine Prüfungen nicht)
CREATE TABLE IF NOT EXISTS index_runs(
    id INTEGER PRIMARY KEY, started_at REAL, finished_at REAL, status TEXT, trigger TEXT, title TEXT,
    corpus_id INTEGER, docs_total INTEGER, docs_done INTEGER, indexed INTEGER, no_text INTEGER, errors INTEGER,
    chunks INTEGER, stopped TEXT, error TEXT, model TEXT, docs TEXT, log TEXT, dismissed INTEGER DEFAULT 0
);
"""

# Projektfarben (wie COLORS in static/js/views/projects.js); ohne gewählte Farbe die nach der ID, fest gespeichert
PROJECT_COLORS = ["#4a43c4", "#0b7285", "#2f7d4f", "#a35c00", "#b3261e", "#7a3fb0", "#2563a8", "#6b5e4f"]
INDEX_RUNS_KEPT = 30


@dataclass
class SearchFilter:
    libs: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)  # "lib:KEY"
    item_keys: list[str] = field(default_factory=list)  # "lib:KEY"
    year_from: int | None = None
    year_to: int | None = None
    tags: list[str] = field(default_factory=list)
    item_types: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)  # text, abstract

    def is_empty(self) -> bool:
        return not (
            self.libs or self.collections or self.item_keys or self.year_from or self.year_to
            or self.tags or self.item_types
        )

    @classmethod
    def from_dict(cls, d: dict | None) -> SearchFilter:
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__ and v not in (None, "")})


_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩]")


def strip_bidi(text: str | None) -> str:
    """Zotero 10 umschliesst Namen in creatorSummary mit Richtungs-Isolatoren (U+2068/U+2069)."""
    return _BIDI.sub("", text or "")


def creator_names(creators: list[dict]) -> str:
    """Namen aller Personen eines Eintrags als Suchtext („Müller Anna Schmid …“)."""
    out = []
    for c in creators or []:
        for k in ("lastName", "firstName", "name"):
            if c.get(k):
                out.append(strip_bidi(str(c[k])))
    return " ".join(out)


def _year(item: dict) -> int | None:
    parsed = (item.get("meta") or {}).get("parsedDate") or ""
    if len(parsed) >= 4 and parsed[:4].isdigit():
        return int(parsed[:4])
    return None


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        # (lib, att_key) des Texts, den die Indexierung gerade liest und einbettet: zählt bis zum Ende als „offen“,
        # nicht als „einzubetten“ (gelesen ist er schon, eingebettet erst teilweise)
        self.busy: tuple[str, str] | None = None
        # Dubletten: Gruppen werden aus den Einträgen berechnet und bis zur nächsten Änderung der Einträge gemerkt;
        # duplicates_gen zählt jede Änderung an Einträgen oder Entscheidungen (für Zwischenspeicher von Kennzahlen)
        self._groups_cache: tuple[int, dict] | None = None
        self.duplicates_gen = 0
        with self._write_lock:
            # executescript verwaltet Transaktionen selbst – daher nicht in write()
            self._connect().executescript(SCHEMA)
        with self.write() as con:
            con.execute("INSERT OR IGNORE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            self._migrate(con)

    @staticmethod
    def _migrate(con: sqlite3.Connection) -> None:
        """Spalten nachrüsten, die nach der ersten Version hinzukamen."""
        cols = {r["name"] for r in con.execute("PRAGMA table_info(attachments)")}
        # page_labels: gedruckte Seitenzahl je PDF-Seite (JSON-Liste, "" = ohne); NULL = vor deren Erkennung indexiert
        for name, typ in (("file_size", "INTEGER"), ("file_mtime", "REAL"), ("page_labels", "TEXT"),
                          ("label_source", "TEXT")):
            if name not in cols:
                con.execute(f"ALTER TABLE attachments ADD COLUMN {name} {typ}")
        if "page_labels" not in cols:
            # Bisher galt die Dateiseite als Seitenzahl: indexierte PDFs einmal neu lesen (nur die Extraktion –
            # unveränderte Abschnitte behalten ihre Einbettungen, siehe replace_chunks)
            con.execute("UPDATE attachments SET status='pending' WHERE status='indexed'"
                        " AND content_type='application/pdf'")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(chunks)")}
        if "page_breaks" not in cols:  # Seitenwechsel im Abschnitt: JSON [[Zeichenposition, PDF-Seite], …]
            con.execute("ALTER TABLE chunks ADD COLUMN page_breaks TEXT")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(libraries)")}
        if "full_synced_at" not in cols:
            con.execute("ALTER TABLE libraries ADD COLUMN full_synced_at REAL")
        if "items_total" not in cols:  # Zahl der Einträge beim Abgleich (Gruppen in Zotero 10 haben keine Version)
            con.execute("ALTER TABLE libraries ADD COLUMN items_total INTEGER DEFAULT 0")
        for table in ("chats", "reviews"):
            cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            if "project_id" not in cols:
                con.execute(f"ALTER TABLE {table} ADD COLUMN project_id INTEGER")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(projects)")}
        # embedding: eigenes Embedding-Modell des Projekts (JSON mit Anbieter, Modell, …), NULL = keins
        for name, typ in (("archived_at", "REAL"), ("position", "INTEGER"), ("embedding", "TEXT")):
            if name not in cols:
                con.execute(f"ALTER TABLE projects ADD COLUMN {name} {typ}")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(index_runs)")}
        if "embedded_docs" not in cols:  # Texte, die in einem Lauf nur (neu) eingebettet wurden
            con.execute("ALTER TABLE index_runs ADD COLUMN embedded_docs INTEGER DEFAULT 0")
        # Farbe fest speichern: Bisher galt ohne gewählte Farbe die nach der ID – nach einem Import (neue ID) wechselte sie
        for r in con.execute("SELECT id FROM projects WHERE color IS NULL OR color=''").fetchall():
            con.execute("UPDATE projects SET color=? WHERE id=?", (PROJECT_COLORS[r["id"] % len(PROJECT_COLORS)], r["id"]))
        # Suchkatalog: Namen der Personen und vollständige Zotero-Daten je Eintrag, Volltextindex über Metadaten
        cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
        fresh_columns = "creator_names" not in cols
        for name in ("creator_names", "data"):
            if name not in cols:
                con.execute(f"ALTER TABLE items ADD COLUMN {name} TEXT")
        if fresh_columns:
            for r in con.execute("SELECT rowid, creators FROM items").fetchall():
                con.execute("UPDATE items SET creator_names=? WHERE rowid=?",
                            (creator_names(json.loads(r["creators"] or "[]")), r["rowid"]))
        has_fts = con.execute("SELECT 1 FROM sqlite_master WHERE name='items_fts'").fetchone()
        con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(title, creator_names, publication, abstract, tags, doi,"
            " content='items', content_rowid='rowid', tokenize=\"unicode61 remove_diacritics 2\")")
        cols6 = "title, creator_names, publication, abstract, tags, doi"
        con.execute(f"CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN "
                    f"INSERT INTO items_fts(rowid, {cols6}) VALUES (new.rowid, new.title, new.creator_names, "
                    f"new.publication, new.abstract, new.tags, new.doi); END;")
        con.execute(f"CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN "
                    f"INSERT INTO items_fts(items_fts, rowid, {cols6}) VALUES ('delete', old.rowid, old.title, "
                    f"old.creator_names, old.publication, old.abstract, old.tags, old.doi); END;")
        con.execute(f"CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN "
                    f"INSERT INTO items_fts(items_fts, rowid, {cols6}) VALUES ('delete', old.rowid, old.title, "
                    f"old.creator_names, old.publication, old.abstract, old.tags, old.doi); "
                    f"INSERT INTO items_fts(rowid, {cols6}) VALUES (new.rowid, new.title, new.creator_names, "
                    f"new.publication, new.abstract, new.tags, new.doi); END;")
        if not has_fts or fresh_columns:
            con.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
        if not con.execute("SELECT 1 FROM meta WHERE key='hex_labels_fixed'").fetchone():
            Store._fix_hex_labels(con)
            con.execute("INSERT OR REPLACE INTO meta VALUES('hex_labels_fixed', '1')")

    @staticmethod
    def _fix_hex_labels(con: sqlite3.Connection) -> None:
        """Seitenbeschriftungen aus PDF-Hex-Text („<FEFF0032>“ statt „2“, vor 0.6.8) einmal lesbar machen – in
        Abschnitten, Anhängen, Auswertungsblättern und gespeicherten Antworten. Betroffene Texte werden zudem neu
        gelesen: Mit lesbaren Werten entscheidet die Seitenzahl-Erkennung womöglich anders (bis dahin bleiben sie
        mit dem bisherigen Text durchsuchbar)."""
        from zotivity.extract.pagenumbers import clean_pdf_label

        hexed = "%<%>%"
        for r in con.execute("SELECT id, page_label FROM chunks WHERE page_label LIKE ?", (hexed,)).fetchall():
            con.execute("UPDATE chunks SET page_label=? WHERE id=?", (clean_pdf_label(r["page_label"]), r["id"]))
        for r in con.execute("SELECT lib, key, page_labels, status FROM attachments WHERE page_labels LIKE ?",
                             (hexed,)).fetchall():
            try:
                labels = [clean_pdf_label(x) for x in json.loads(r["page_labels"] or "[]")]
            except ValueError:
                continue
            con.execute("UPDATE attachments SET page_labels=?, status=? WHERE lib=? AND key=?",
                        (json.dumps(labels), "pending" if r["status"] == "indexed" else r["status"], r["lib"], r["key"]))

        def clean_json(value, keys=("page_label", "seite")):
            if isinstance(value, dict):
                return {k: clean_pdf_label(v) if k in keys and isinstance(v, str) else clean_json(v, keys)
                        for k, v in value.items()}
            if isinstance(value, list):
                return [clean_json(v, keys) for v in value]
            return value

        for table, col, where in (("sheets", "sheet", "rowid"), ("chat_messages", "sources", "id")):
            for r in con.execute(f"SELECT {where} AS rid, {col} AS val FROM {table} WHERE {col} LIKE ?",
                                 ("%<FEFF%",)).fetchall():
                try:
                    data = json.loads(r["val"] or "null")
                except ValueError:
                    continue
                con.execute(f"UPDATE {table} SET {col}=? WHERE {where}=?",
                            (json.dumps(clean_json(data), ensure_ascii=False), r["rid"]))

    # -- Verbindung ----------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=60, check_same_thread=False, isolation_level=None)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("PRAGMA foreign_keys=OFF")
            con.execute("PRAGMA temp_store=MEMORY")
            con.execute("PRAGMA cache_size=-65536")
            self._local.con = con
        return con

    @property
    def con(self) -> sqlite3.Connection:
        return self._connect()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        with self._write_lock:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None

    # -- Meta ------------------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.write() as con:
            con.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (key, value))

    def library_state(self, lib: str) -> dict:
        row = self.con.execute("SELECT * FROM libraries WHERE lib=?", (lib,)).fetchone()
        return dict(row) if row else {"lib": lib, "items_version": 0, "collections_version": 0, "server_id": None,
                                      "synced_at": None, "full_synced_at": None, "name": None, "items_total": 0}

    def set_library_state(self, lib: str, **values) -> None:
        state = self.library_state(lib)
        state.update(values)
        with self.write() as con:
            con.execute(
                "INSERT OR REPLACE INTO libraries(lib, name, server_id, items_version, collections_version, synced_at,"
                " full_synced_at, items_total) VALUES(?,?,?,?,?,?,?,?)",
                (lib, state.get("name"), state.get("server_id"), state.get("items_version", 0),
                 state.get("collections_version", 0), state.get("synced_at"), state.get("full_synced_at"),
                 state.get("items_total") or 0),
            )

    def library_names(self) -> dict[str, str]:
        return {r["lib"]: r["name"] for r in self.con.execute("SELECT lib, name FROM libraries") if r["name"]}

    def reset_library(self, lib: str) -> None:
        """Bei neuer Zotero-Installation (andere Server-ID): Versionsstände verwerfen."""
        with self.write() as con:
            con.execute("UPDATE libraries SET items_version=0, collections_version=0, synced_at=NULL,"
                        " full_synced_at=NULL WHERE lib=?", (lib,))

    # -- Sammlungen ------------------------------------------------------------------
    def replace_collections(self, lib: str, collections: list[dict]) -> None:
        with self.write() as con:
            con.execute("DELETE FROM collections WHERE lib=?", (lib,))
            con.executemany(
                "INSERT INTO collections VALUES(?,?,?,?,?)",
                [
                    (lib, c["key"], c["data"].get("name", ""), c["data"].get("parentCollection") or None,
                     (c.get("meta") or {}).get("numItems"))
                    for c in collections
                ],
            )

    def collections(self, lib: str | None = None) -> list[dict]:
        sql = "SELECT * FROM collections" + (" WHERE lib=?" if lib else "") + " ORDER BY name COLLATE NOCASE"
        return [dict(r) for r in self.con.execute(sql, (lib,) if lib else ())]

    def collection_descendants(self, lib: str, key: str) -> set[str]:
        rows = self.con.execute("SELECT key, parent FROM collections WHERE lib=?", (lib,)).fetchall()
        children: dict[str, list[str]] = {}
        for r in rows:
            children.setdefault(r["parent"], []).append(r["key"])
        out, stack = set(), [key]
        while stack:
            k = stack.pop()
            if k in out:
                continue
            out.add(k)
            stack.extend(children.get(k, []))
        return out

    # -- Einträge --------------------------------------------------------------------
    _ITEM_COLS = ("lib", "key", "version", "item_type", "title", "creators", "creator_summary", "year", "date",
                  "publication", "abstract", "doi", "url", "tags", "collections", "language", "updated_at",
                  "creator_names", "data")

    def upsert_items(self, lib: str, items: Iterable[dict]) -> int:
        rows = []
        now = time.time()
        for it in items:
            d = it.get("data", {})
            if d.get("itemType") in ("note", "annotation"):
                continue
            rows.append((
                lib, it["key"], it.get("version", 0), d.get("itemType"), d.get("title") or d.get("filename") or "",
                json.dumps(d.get("creators", []), ensure_ascii=False),
                strip_bidi((it.get("meta") or {}).get("creatorSummary", "")), _year(it), d.get("date", ""),
                d.get("publicationTitle") or d.get("bookTitle") or d.get("proceedingsTitle")
                or d.get("websiteTitle") or d.get("publisher") or "",
                d.get("abstractNote", ""), d.get("DOI", ""), d.get("url", ""),
                json.dumps([t.get("tag") for t in d.get("tags", [])], ensure_ascii=False),
                json.dumps(d.get("collections", [])), d.get("language", ""), now,
                creator_names(d.get("creators", [])), json.dumps(d, ensure_ascii=False),
            ))
        if rows:
            cols = ", ".join(self._ITEM_COLS)
            updates = ", ".join(f"{c}=excluded.{c}" for c in self._ITEM_COLS[2:])
            with self.write() as con:
                # ON CONFLICT … DO UPDATE behält die rowid – der Volltextindex der Metadaten bleibt stimmig
                con.executemany(
                    f"INSERT INTO items({cols}) VALUES({','.join('?' * len(self._ITEM_COLS))})"
                    f" ON CONFLICT(lib, key) DO UPDATE SET {updates}", rows)
            self.duplicates_gen += 1
        return len(rows)

    def item(self, lib: str, key: str) -> dict | None:
        row = self.con.execute("SELECT * FROM items WHERE lib=? AND key=?", (lib, key)).fetchone()
        return _item_row(row) if row else None

    def items_of_type(self, item_type: str) -> list[dict]:
        """Kurzangaben aller Einträge einer Zotero-Eintragsart (Personen entpackt), etwa für Beispiele im CSL-Editor."""
        rows = self.con.execute("SELECT lib, key, creators, year, publication, doi, url, updated_at FROM items "
                                "WHERE item_type=?", (item_type,)).fetchall()
        return [{**dict(r), "creators": json.loads(r["creators"] or "[]")} for r in rows]

    def items(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict]:
        out: dict[tuple[str, str], dict] = {}
        keys = list(keys)
        for i in range(0, len(keys), 400):
            batch = keys[i : i + 400]
            q = " OR ".join(["(lib=? AND key=?)"] * len(batch))
            params = [x for pair in batch for x in pair]
            for row in self.con.execute(f"SELECT * FROM items WHERE {q}", params):
                out[(row["lib"], row["key"])] = _item_row(row)
        return out

    _REMOVED_COLS = ("lib", "key", "item_type", "title", "creators", "creator_summary", "year", "date", "publication",
                     "doi", "data")

    def delete_items(self, lib: str, keys: Iterable[str]) -> None:
        keys = list(keys)
        cols = ", ".join(self._REMOVED_COLS)
        with self.write() as con:
            for k in keys:
                # Kurzangaben behalten: Belege auf den Eintrag bleiben lesbar (references.py)
                con.execute(f"INSERT OR REPLACE INTO removed_items({cols}, removed_at) SELECT {cols}, ? FROM items"
                            " WHERE lib=? AND key=?", (time.time(), lib, k))
                con.execute("DELETE FROM chunks WHERE lib=? AND item_key=?", (lib, k))
                con.execute("DELETE FROM items WHERE lib=? AND key=?", (lib, k))
                con.execute("DELETE FROM sheets WHERE lib=? AND item_key=?", (lib, k))
        self.duplicates_gen += 1

    def item_keys(self, lib: str) -> set[str]:
        return {r[0] for r in self.con.execute("SELECT key FROM items WHERE lib=?", (lib,))}

    # -- In Zotero gelöschte Einträge (Kurzangaben für Belege) ------------------------------------
    def removed_items(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict]:
        """Kurzangaben gelöschter Einträge im Format von items() (Personen und Daten entpackt), mit removed=True."""
        out: dict[tuple[str, str], dict] = {}
        keys = list(keys)
        for i in range(0, len(keys), 400):
            batch = keys[i: i + 400]
            q = " OR ".join(["(lib=? AND key=?)"] * len(batch))
            for r in self.con.execute(f"SELECT * FROM removed_items WHERE {q}", [x for pair in batch for x in pair]):
                d = dict(r)
                d["creators"] = json.loads(d["creators"] or "[]")
                d["data"] = json.loads(d["data"] or "{}")
                d.update(tags=[], collections=[], removed=True)
                out[(d["lib"], d["key"])] = d
        return out

    def put_removed_item(self, lib: str, item: dict) -> None:
        """Kurzangaben aus Zotero (z. B. eines Eintrags im Papierkorb, der vor dieser Version entfernt wurde)."""
        d = item.get("data") or {}
        with self.write() as con:
            con.execute(
                f"INSERT OR REPLACE INTO removed_items({', '.join(self._REMOVED_COLS)}, removed_at)"
                f" VALUES({','.join('?' * (len(self._REMOVED_COLS) + 1))})",
                (lib, item["key"], d.get("itemType"), d.get("title") or "",
                 json.dumps(d.get("creators", []), ensure_ascii=False),
                 strip_bidi((item.get("meta") or {}).get("creatorSummary", "")), _year(item), d.get("date", ""),
                 d.get("publicationTitle") or d.get("bookTitle") or d.get("proceedingsTitle") or "", d.get("DOI", ""),
                 json.dumps(d, ensure_ascii=False), time.time()))

    def replace_review_doc(self, review_id: int, old: tuple[str, str], new: tuple[str, str]) -> None:
        """Ein Text der Auswahl eines Forschungsstands wird durch eine andere Kopie desselben Werks ersetzt."""
        with self.write() as con:
            row = con.execute("SELECT * FROM review_docs WHERE review_id=? AND lib=? AND item_key=?",
                              (review_id, *old)).fetchone()
            if not row:
                return
            if con.execute("SELECT 1 FROM review_docs WHERE review_id=? AND lib=? AND item_key=?",
                           (review_id, *new)).fetchone():
                con.execute("DELETE FROM review_docs WHERE review_id=? AND lib=? AND item_key=?", (review_id, *old))
                if row["included"]:
                    con.execute("UPDATE review_docs SET included=1 WHERE review_id=? AND lib=? AND item_key=?",
                                (review_id, *new))
            else:
                con.execute("UPDATE review_docs SET lib=?, item_key=? WHERE review_id=? AND lib=? AND item_key=?",
                            (*new, review_id, *old))

    # -- Dubletten (siehe index/duplicates.py) ---------------------------------------------------
    def work_rows(self, table: str = "items") -> list[dict]:
        """Angaben, an denen ein Werk erkannt wird (DOI, Titel, Personen, Jahr) – für Dubletten und gelöschte Einträge."""
        from zotivity.index.duplicates import normalize_doi

        rows = []
        for r in self.con.execute(f"SELECT lib, key, item_type, title, creators, year, doi, data FROM {table}"):
            extra = ""
            if not normalize_doi(r["doi"]) and r["data"] and "DOI" in r["data"]:
                try:  # DOI im Feld Extra („DOI: 10.…“), z. B. bei Büchern und Kapiteln
                    extra = json.loads(r["data"]).get("extra") or ""
                except ValueError:
                    pass
            rows.append({"lib": r["lib"], "key": r["key"], "item_type": r["item_type"], "title": r["title"],
                         "creators": json.loads(r["creators"] or "[]"), "year": r["year"], "doi": r["doi"],
                         "extra": extra})
        return rows

    def duplicate_groups(self) -> dict[str, list[tuple[str, str]]]:
        """Werke mit mehreren Einträgen, berechnet aus den Metadaten (bis zur nächsten Änderung gemerkt)."""
        from zotivity.index.duplicates import find_groups

        cached = self._groups_cache
        if cached and cached[0] == self.duplicates_gen:
            return cached[1]
        gen = self.duplicates_gen
        groups = find_groups(self.work_rows())
        self._groups_cache = (gen, groups)
        return groups

    def duplicate_choices(self) -> dict[str, dict]:
        return {r["work"]: dict(r) for r in self.con.execute("SELECT * FROM duplicate_choices")}

    def set_duplicate_choice(self, work: str, mode: str | None, lib: str | None = None,
                             item_key: str | None = None) -> None:
        """mode: user (mit lib/item_key), rule, separate; None löscht die Entscheidung (gilt wieder als neu)."""
        with self.write() as con:
            if mode is None:
                con.execute("DELETE FROM duplicate_choices WHERE work=?", (work,))
            else:
                con.execute("INSERT OR REPLACE INTO duplicate_choices VALUES(?,?,?,?,?)",
                            (work, mode, lib if mode == "user" else None, item_key if mode == "user" else None,
                             time.time()))
        self.duplicates_gen += 1

    def attachments_of(self, items: Iterable[tuple[str, str]]) -> dict[tuple[str, str], list[dict]]:
        """Anhänge je Eintrag (lib, key) – ohne Schnappschüsse neben einer PDF und ohne nicht lesbare Typen."""
        out: dict[tuple[str, str], list[dict]] = {}
        keys = list(items)
        for i in range(0, len(keys), 400):
            batch = keys[i: i + 400]
            q = " OR ".join(["(lib=? AND parent=?)"] * len(batch))
            params = [x for pair in batch for x in pair]
            for r in self.con.execute(
                    "SELECT lib, parent, key, status, n_chunks, page_labels FROM attachments"
                    f" WHERE status NOT IN ('skipped','redundant') AND ({q})", params):
                out.setdefault((r["lib"], r["parent"]), []).append(dict(r))
        return out

    # -- Anhänge ---------------------------------------------------------------------
    def upsert_attachment(self, lib: str, att: dict, path: str | None, supported: bool = True) -> None:
        """Anhang eintragen. Nicht verarbeitbare Typen (z. B. Links, Bilder) gelten als 'skipped',
        bereits verarbeitete bleiben unverändert, solange sich die Datei (MD5) nicht geändert hat."""
        d = att.get("data", {})
        parent = d.get("parentItem") or att["key"]
        with self.write() as con:
            old = con.execute("SELECT md5, status, indexed_md5 FROM attachments WHERE lib=? AND key=?",
                              (lib, att["key"])).fetchone()
            if not supported:
                status = "skipped"
            elif old is None or old["status"] in ("pending", "skipped"):
                status = "pending"
            elif d.get("md5") and old["indexed_md5"] and d["md5"] != old["indexed_md5"]:
                status = "pending"
            else:
                status = old["status"]
            con.execute(
                "INSERT INTO attachments(lib, key, parent, version, title, content_type, link_mode, path, md5, mtime, status)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(lib, key) DO UPDATE SET parent=excluded.parent, version=excluded.version,"
                " title=excluded.title, content_type=excluded.content_type, link_mode=excluded.link_mode,"
                " path=excluded.path, md5=excluded.md5, mtime=excluded.mtime, status=excluded.status",
                (lib, att["key"], parent, att.get("version", 0), d.get("title", ""), d.get("contentType", ""),
                 d.get("linkMode", ""), path, d.get("md5"), d.get("mtime"), status),
            )

    def skipped_attachments(self, lib: str, content_types: list[str]) -> list[str]:
        """Übersprungene Anhänge, deren Dateityp inzwischen lesbar ist (z. B. Word ab 0.9.0)."""
        ph = ",".join("?" * len(content_types)) or "''"
        return [r[0] for r in self.con.execute(
            f"SELECT key FROM attachments WHERE lib=? AND status='skipped' AND link_mode!='linked_url'"
            f" AND content_type IN ({ph})", [lib, *content_types])]

    def activate_attachment(self, lib: str, key: str, path: str | None) -> None:
        """Übersprungenen Anhang zum Lesen vormerken."""
        with self.write() as con:
            con.execute("UPDATE attachments SET status='pending', path=? WHERE lib=? AND key=? AND status='skipped'",
                        (path, lib, key))

    def attachment(self, lib: str, key: str) -> dict | None:
        row = self.con.execute("SELECT * FROM attachments WHERE lib=? AND key=?", (lib, key)).fetchone()
        return dict(row) if row else None

    def attachments_for_item(self, lib: str, item_key: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM attachments WHERE lib=? AND parent=? ORDER BY key", (lib, item_key))]

    def attachment_keys(self, lib: str) -> set[str]:
        return {r[0] for r in self.con.execute("SELECT key FROM attachments WHERE lib=?", (lib,))}

    def processed_attachments(self, lib: str) -> list[dict]:
        """Bereits verarbeitete Anhänge mit Dateipfad (für die Änderungserkennung über Grösse/Zeit/MD5)."""
        return [dict(r) for r in self.con.execute(
            "SELECT key, path, file_size, file_mtime, indexed_md5 FROM attachments WHERE lib=? AND path IS NOT NULL"
            " AND status IN ('indexed','no_text','error')", (lib,))]

    def set_file_stat(self, lib: str, key: str, size: int, mtime: float) -> None:
        with self.write() as con:
            con.execute("UPDATE attachments SET file_size=?, file_mtime=? WHERE lib=? AND key=?",
                        (size, mtime, lib, key))

    def backup(self, dest: Path) -> None:
        """Konsistente Kopie der Datenbank (SQLite-Sicherungsschnittstelle), auch während des Betriebs."""
        import os

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        target = sqlite3.connect(tmp)
        try:
            with self._write_lock:
                self.con.backup(target)
        finally:
            target.close()
        os.replace(tmp, dest)

    def mark_pending(self, lib: str, keys: Iterable[str]) -> None:
        with self.write() as con:
            con.executemany("UPDATE attachments SET status='pending' WHERE lib=? AND key=?",
                            [(lib, k) for k in keys])

    def count_pending(self, scope: set[tuple[str, str]] | None) -> int:
        rows = self.con.execute("SELECT lib, parent FROM attachments WHERE status='pending'").fetchall()
        if scope is None:
            return len(rows)
        return sum(1 for r in rows if (r["lib"], r["parent"]) in scope)

    def delete_attachments(self, lib: str, keys: Iterable[str]) -> None:
        with self.write() as con:
            for k in keys:
                con.execute("DELETE FROM chunks WHERE lib=? AND att_key=?", (lib, k))
                con.execute("DELETE FROM attachments WHERE lib=? AND key=?", (lib, k))

    def set_attachment_status(self, lib: str, key: str, status: str, **values) -> None:
        cols = ["status=?"]
        params: list[Any] = [status]
        for k, v in values.items():
            cols.append(f"{k}=?")
            params.append(v)
        params += [lib, key]
        with self.write() as con:
            con.execute(f"UPDATE attachments SET {', '.join(cols)} WHERE lib=? AND key=?", params)

    # Webseiten-Schnappschüsse (HTML) neben einer PDF/EPUB desselben Eintrags würden den Text doppelt (samt Menüs und
    # Literaturliste der Verlagsseite) in den Index bringen. Sie gelten als 'redundant', solange die PDF/EPUB lesbar
    # ist oder noch gelesen wird; fällt sie weg oder liefert sie keinen Text, wird der Schnappschuss wieder verarbeitet.
    SNAPSHOT_TYPES = ("text/html", "application/xhtml+xml")
    FULLTEXT_TYPES = ("application/pdf", "application/epub+zip")
    REDUNDANT_MESSAGE = "Schnappschuss nicht nötig – der Eintrag hat eine PDF"

    def reconcile_snapshots(self) -> int:
        """Status der Schnappschüsse an ihre Geschwister-Anhänge anpassen. Rückgabe: Zahl der Schnappschüsse,
        deren Abschnitte entfernt wurden (dann muss der Vektorindex neu geladen werden)."""
        snap = ",".join(f"'{t}'" for t in self.SNAPSHOT_TYPES)
        full = ",".join(f"'{t}'" for t in self.FULLTEXT_TYPES)
        has_fulltext = (
            "EXISTS (SELECT 1 FROM attachments b WHERE b.lib=attachments.lib AND b.parent=attachments.parent"
            f" AND b.key != attachments.key AND b.content_type IN ({full}) AND b.status IN ('pending','indexed'))")
        with self.write() as con:
            con.execute(f"UPDATE attachments SET status='pending', error=NULL WHERE status='redundant' AND NOT {has_fulltext}")
            where = (f"content_type IN ({snap}) AND parent != key AND status IN ('pending','indexed','no_text','error')"
                     f" AND {has_fulltext}")
            rows = con.execute(f"SELECT lib, key, parent, status FROM attachments WHERE {where}").fetchall()
            con.execute(f"UPDATE attachments SET status='redundant', error=?, n_chunks=0 WHERE {where}",
                        (self.REDUNDANT_MESSAGE,))
        removed = 0
        for r in rows:
            if r["status"] == "indexed":
                self.replace_chunks(r["lib"], r["parent"], r["key"], [])
                removed += 1
        return removed

    def pending_attachments(self, scope: set[tuple[str, str]] | None, content_types: list[str]) -> list[dict]:
        """Anhänge, deren Text (neu) extrahiert werden muss."""
        ph = ",".join("?" * len(content_types)) or "''"
        rows = self.con.execute(
            f"SELECT * FROM attachments WHERE status='pending' AND content_type IN ({ph}) ORDER BY lib, parent",
            content_types,
        ).fetchall()
        out = [dict(r) for r in rows]
        if scope is not None:
            out = [r for r in out if (r["lib"], r["parent"]) in scope]
        return out

    def reset_attachments(self, scope: set[tuple[str, str]] | None = None, statuses=("error", "no_text")) -> int:
        ph = ",".join("?" * len(statuses))
        rows = self.con.execute(f"SELECT lib, key, parent FROM attachments WHERE status IN ({ph})", statuses).fetchall()
        n = 0
        with self.write() as con:
            for r in rows:
                if scope is None or (r["lib"], r["parent"]) in scope:
                    con.execute("UPDATE attachments SET status='pending', error=NULL WHERE lib=? AND key=?",
                                (r["lib"], r["key"]))
                    n += 1
        return n

    # -- Abschnitte ------------------------------------------------------------------
    def replace_chunks(self, lib: str, item_key: str, att_key: str, chunks: list[Chunk]) -> list[int]:
        """Abschnitte eines Anhangs ersetzen. Ist der Text unverändert (z. B. erneutes Lesen nur für die
        Seitenzahlen), werden nur die Seitenangaben aktualisiert – die Einbettungen bleiben erhalten."""
        with self.write() as con:
            old = con.execute("SELECT id, text FROM chunks WHERE lib=? AND att_key=? ORDER BY ord",
                              (lib, att_key)).fetchall()
            if old and len(old) == len(chunks) and all(o["text"] == c.text for o, c in zip(old, chunks)):
                for o, c in zip(old, chunks):
                    breaks = getattr(c, "breaks", None)
                    con.execute("UPDATE chunks SET item_key=?, ord=?, kind=?, page_start=?, page_end=?, page_label=?,"
                                " page_breaks=? WHERE id=?",
                                (item_key, c.ord, c.kind, c.page_start, c.page_end, c.page_label,
                                 json.dumps(breaks) if breaks else None, o["id"]))
                return [o["id"] for o in old]
            con.execute("DELETE FROM chunks WHERE lib=? AND att_key=?", (lib, att_key))
            ids = []
            for c in chunks:
                breaks = getattr(c, "breaks", None)
                cur = con.execute(
                    "INSERT INTO chunks(lib, item_key, att_key, ord, kind, page_start, page_end, page_label, text,"
                    " page_breaks) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (lib, item_key, att_key, c.ord, c.kind, c.page_start, c.page_end, c.page_label, c.text,
                     json.dumps(breaks) if breaks else None),
                )
                ids.append(cur.lastrowid)
        return ids

    def page_labels(self, lib: str, att_key: str) -> list[str] | None:
        """Gedruckte Seitenzahl je PDF-Seite eines Anhangs (None = noch ohne Seitenzahl-Erkennung indexiert)."""
        row = self.con.execute("SELECT page_labels FROM attachments WHERE lib=? AND key=?", (lib, att_key)).fetchone()
        if not row or row[0] is None:
            return None
        try:
            return [str(x or "") for x in json.loads(row[0])]
        except ValueError:
            return None

    def sync_abstract_chunk(self, lib: str, item_key: str, abstract_chunk: Chunk | None) -> None:
        """Abstract als eigener Abschnitt (att_key = ''), nur bei Änderung neu schreiben."""
        row = self.con.execute(
            "SELECT id, text FROM chunks WHERE lib=? AND item_key=? AND att_key='' AND kind='abstract'",
            (lib, item_key),
        ).fetchone()
        if abstract_chunk is None:
            if row:
                with self.write() as con:
                    con.execute("DELETE FROM chunks WHERE id=?", (row["id"],))
            return
        if row and row["text"] == abstract_chunk.text:
            return
        self.replace_chunks(lib, item_key, "", [abstract_chunk])

    def chunk_rows(self, ids: Iterable[int]) -> dict[int, dict]:
        ids = list(ids)
        out: dict[int, dict] = {}
        for i in range(0, len(ids), 800):
            batch = ids[i : i + 800]
            ph = ",".join("?" * len(batch))
            for r in self.con.execute(f"SELECT * FROM chunks WHERE id IN ({ph})", batch):
                out[r["id"]] = dict(r)
        return out

    def neighbor_chunks(self, lib: str, att_key: str, ord_: int, n: int) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM chunks WHERE lib=? AND att_key=? AND ord BETWEEN ? AND ? ORDER BY ord",
            (lib, att_key, ord_ - n, ord_ + n))]

    def document_chunks(self, lib: str, item_key: str) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM chunks WHERE lib=? AND item_key=? ORDER BY att_key, ord", (lib, item_key))]

    _DOC_CHUNKS = ("FROM chunks c LEFT JOIN embeddings e ON e.space=? AND e.chunk_id=c.id"
                   " WHERE e.chunk_id IS NULL AND c.kind != 'references' AND c.lib=?"
                   " AND (c.att_key=? OR (c.item_key=? AND c.att_key=''))")

    def document_chunks_to_embed(self, space: str, lib: str, att_key: str, item_key: str, limit: int) -> list[dict]:
        """Noch nicht eingebettete Abschnitte eines Dokuments samt Abstract des Eintrags."""
        return [dict(r) for r in self.con.execute(
            f"SELECT c.* {self._DOC_CHUNKS} ORDER BY c.id LIMIT ?", (space, lib, att_key, item_key, limit))]

    def count_document_chunks_to_embed(self, space: str, lib: str, att_key: str, item_key: str) -> int:
        return self.con.execute(f"SELECT COUNT(*) {self._DOC_CHUNKS}", (space, lib, att_key, item_key)).fetchone()[0]

    # -- Embeddings --------------------------------------------------------------------
    def ensure_space(self, space: str, provider: str, model: str, dim: int, params: dict) -> None:
        with self.write() as con:
            con.execute(
                "INSERT OR IGNORE INTO spaces VALUES(?,?,?,?,?,?)",
                (space, provider, model, dim, json.dumps(params), time.time()),
            )

    def spaces(self) -> list[dict]:
        rows = self.con.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM embeddings e WHERE e.space=s.space) AS n FROM spaces s"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_space(self, space: str) -> None:
        with self.write() as con:
            con.execute("DELETE FROM embeddings WHERE space=?", (space,))
            con.execute("DELETE FROM spaces WHERE space=?", (space,))

    def put_embeddings(self, space: str, ids: list[int], vecs: np.ndarray) -> None:
        vecs = np.asarray(vecs, dtype=np.float16)
        with self.write() as con:
            # Abschnitt könnte inzwischen gelöscht sein – nur existierende speichern
            ph = ",".join("?" * len(ids))
            alive = {r[0] for r in con.execute(f"SELECT id FROM chunks WHERE id IN ({ph})", ids)}
            con.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES(?,?,?)",
                [(space, cid, vecs[i].tobytes()) for i, cid in enumerate(ids) if cid in alive],
            )

    def load_vectors(self, space: str, dim: int) -> tuple[np.ndarray, np.ndarray]:
        ids: list[int] = []
        blobs: list[bytes] = []
        for cid, blob in self.con.execute(
            "SELECT chunk_id, vec FROM embeddings WHERE space=? ORDER BY chunk_id", (space,)
        ):
            ids.append(cid)
            blobs.append(blob)
        if not ids:
            return np.zeros(0, dtype=np.int64), np.zeros((0, dim), dtype=np.float16)
        mat = np.frombuffer(b"".join(blobs), dtype=np.float16).reshape(len(ids), dim)
        return np.asarray(ids, dtype=np.int64), mat

    # -- Filter & Volltextsuche ----------------------------------------------------------
    def allowed_items(self, f: SearchFilter) -> set[tuple[str, str]] | None:
        """Menge (lib, item_key), die den Filter erfüllt; None = keine Einschränkung."""
        if f.is_empty():
            return None
        where, params = [], []
        if f.libs:
            where.append(f"lib IN ({','.join('?' * len(f.libs))})")
            params += f.libs
        if f.year_from:
            where.append("year >= ?")
            params.append(f.year_from)
        if f.year_to:
            where.append("year <= ?")
            params.append(f.year_to)
        if f.item_types:
            where.append(f"item_type IN ({','.join('?' * len(f.item_types))})")
            params += f.item_types
        sql = "SELECT lib, key, tags, collections FROM items" + (" WHERE " + " AND ".join(where) if where else "")
        rows = self.con.execute(sql, params).fetchall()

        col_sets: dict[str, set[str]] = {}
        whole_libs: set[str] = set()  # "lib:*" = ganze Bibliothek
        explicit = {tuple(k.split(":", 1)) for k in f.item_keys}
        for c in f.collections:
            lib, _, key = c.partition(":")
            if key == "*":
                whole_libs.add(lib)
            elif key.startswith("@"):  # "lib:@KEY" = einzelner Eintrag (z. B. aus der Suche in einen Korpus)
                explicit.add((lib, key[1:]))
            else:
                col_sets.setdefault(lib, set()).update(self.collection_descendants(lib, key))
        tags = {t.lower() for t in f.tags}

        out: set[tuple[str, str]] = set()
        for r in rows:
            key = (r["lib"], r["key"])
            ok = True
            if f.collections or f.item_keys:
                in_col = r["lib"] in whole_libs or bool(
                    col_sets.get(r["lib"], set()) & set(json.loads(r["collections"] or "[]")))
                ok = in_col or key in explicit
            if ok and tags:
                ok = bool(tags & {t.lower() for t in json.loads(r["tags"] or "[]")})
            if ok:
                out.add(key)
        return out

    def chunk_ids_for_items(self, items: set[tuple[str, str]]) -> np.ndarray:
        if not items:
            return np.zeros(0, dtype=np.int64)
        con = self.con
        con.execute("CREATE TEMP TABLE IF NOT EXISTS _allowed(lib TEXT, key TEXT)")
        con.execute("DELETE FROM _allowed")
        con.executemany("INSERT INTO _allowed VALUES(?,?)", list(items))
        ids = [r[0] for r in con.execute(
            "SELECT c.id FROM chunks c JOIN _allowed a ON a.lib=c.lib AND a.key=c.item_key")]
        con.execute("DELETE FROM _allowed")
        return np.asarray(sorted(ids), dtype=np.int64)

    def chunk_ids_excluding(self, items: set[tuple[str, str]]) -> np.ndarray:
        """Alle Abschnitte ausser denen dieser Einträge (Suche ohne Filter, aber ohne nicht gewählte Dubletten)."""
        con = self.con
        con.execute("CREATE TEMP TABLE IF NOT EXISTS _excluded(lib TEXT, key TEXT)")
        con.execute("DELETE FROM _excluded")
        con.executemany("INSERT INTO _excluded VALUES(?,?)", list(items))
        ids = [r[0] for r in con.execute(
            "SELECT c.id FROM chunks c LEFT JOIN _excluded x ON x.lib=c.lib AND x.key=c.item_key WHERE x.lib IS NULL")]
        con.execute("DELETE FROM _excluded")
        return np.asarray(sorted(ids), dtype=np.int64)

    def fts_search(self, match_query: str, limit: int, allowed_ids: np.ndarray | None = None) -> list[tuple[int, float]]:
        """BM25-Suche. Rückgabe [(chunk_id, score)], höherer Score = besser."""
        if not match_query:
            return []
        try:
            if allowed_ids is None:
                rows = self.con.execute(
                    "SELECT f.rowid, bm25(chunks_fts) AS s FROM chunks_fts f JOIN chunks c ON c.id = f.rowid"
                    " WHERE chunks_fts MATCH ? AND c.kind != 'references' ORDER BY s LIMIT ?",
                    (match_query, limit),
                ).fetchall()
            else:
                con = self.con
                con.execute("CREATE TEMP TABLE IF NOT EXISTS _ids(id INTEGER PRIMARY KEY)")
                con.execute("DELETE FROM _ids")
                con.executemany("INSERT INTO _ids VALUES(?)", ((int(i),) for i in allowed_ids))
                rows = con.execute(
                    "SELECT f.rowid, bm25(chunks_fts) AS s FROM chunks_fts f JOIN _ids i ON i.id = f.rowid"
                    " JOIN chunks c ON c.id = f.rowid"
                    " WHERE chunks_fts MATCH ? AND c.kind != 'references' ORDER BY s LIMIT ?",
                    (match_query, limit),
                ).fetchall()
                con.execute("DELETE FROM _ids")
        except sqlite3.OperationalError:
            return []
        return [(r[0], -r[1]) for r in rows]

    # -- Statistik ---------------------------------------------------------------------
    def stats(self, space: str | None = None) -> dict:
        con = self.con
        by_status = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM attachments GROUP BY status")}
        out = {
            "items": con.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            "attachments": sum(by_status.values()),
            "attachments_by_status": by_status,
            "chunks": con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "references": con.execute("SELECT COUNT(*) FROM chunks WHERE kind='references'").fetchone()[0],
            "collections": con.execute("SELECT COUNT(*) FROM collections").fetchone()[0],
            "db_bytes": sum(p.stat().st_size for p in (self.path, self.path.with_name(self.path.name + "-wal"))
                            if p.exists()),
        }
        if space:
            out["embedded"] = con.execute("SELECT COUNT(*) FROM embeddings WHERE space=?", (space,)).fetchone()[0]
        return out

    # -- Verlauf der Indexierläufe ------------------------------------------------------------
    _RUN_COLS = ("started_at", "finished_at", "status", "trigger", "title", "corpus_id", "docs_total", "docs_done",
                 "indexed", "no_text", "errors", "chunks", "stopped", "error", "model", "embedded_docs")

    def add_index_run(self, run: dict, docs: list[dict], log: list[str]) -> int:
        with self.write() as con:
            rid = con.execute(
                f"INSERT INTO index_runs({', '.join(self._RUN_COLS)}, docs, log) VALUES({','.join('?' * (len(self._RUN_COLS) + 2))})",
                [run.get(c) for c in self._RUN_COLS] + [json.dumps(docs, ensure_ascii=False), "\n".join(log)]).lastrowid
            con.execute("DELETE FROM index_runs WHERE id NOT IN (SELECT id FROM index_runs ORDER BY id DESC LIMIT ?)",
                        (INDEX_RUNS_KEPT,))
            return rid

    def recent_activity(self) -> dict[tuple[str, str], float]:
        """Je Eintrag (lib, key): wann ein Lauf seinen Text zuletzt gelesen oder eingebettet hat (aus dem Verlauf der
        Läufe; erfasst auch reines Einbetten, das indexed_at nicht ändert). Bis zum nächsten Lauf gemerkt."""
        last = self.con.execute("SELECT MAX(id) FROM index_runs").fetchone()[0]
        cached = getattr(self, "_activity_cache", None)
        if cached and cached[0] == last:
            return cached[1]
        out: dict[tuple[str, str], float] = {}
        for r in self.con.execute("SELECT finished_at, docs FROM index_runs ORDER BY id DESC"):
            try:
                docs = json.loads(r["docs"] or "[]")
            except ValueError:
                continue
            for d in docs:
                if d.get("status") in ("indexed", "embedded") and d.get("lib") and d.get("parent"):
                    out.setdefault((d["lib"], d["parent"]), r["finished_at"] or 0.0)
        self._activity_cache = (last, out)
        return out

    def index_runs(self, limit: int = 10) -> list[dict]:
        cols = ", ".join(("id", *self._RUN_COLS, "dismissed"))
        return [dict(r) for r in self.con.execute(f"SELECT {cols} FROM index_runs ORDER BY id DESC LIMIT ?", (limit,))]

    def index_run(self, run_id: int) -> dict | None:
        row = self.con.execute("SELECT * FROM index_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["docs"] = json.loads(d["docs"] or "[]")
        d["log"] = (d["log"] or "").splitlines()
        return d

    def dismiss_index_run(self, run_id: int) -> None:
        with self.write() as con:
            con.execute("UPDATE index_runs SET dismissed=1 WHERE id=?", (run_id,))

    def errors(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT a.lib, a.key, a.parent, a.status, a.error, a.path, i.title FROM attachments a"
            " LEFT JOIN items i ON i.lib=a.lib AND i.key=a.parent"
            " WHERE a.status IN ('error','no_text') ORDER BY a.status, i.title LIMIT ?", (limit,))]

    # -- Projekte -----------------------------------------------------------------------------
    # Ein Projekt bündelt Korpora (geteilt, m:n), Chats und Forschungsstände. Der Index ist für alle gemeinsam.
    def projects(self) -> list[dict]:
        out = []
        # Feste Reihenfolge, damit Kacheln beim Öffnen nicht springen: von Hand angeordnet (position),
        # neue Projekte danach in der Reihenfolge der Anlage
        for r in self.con.execute("SELECT * FROM projects ORDER BY position IS NULL, position, id"):
            d = dict(r)
            d["embedding"] = json.loads(d["embedding"]) if d.get("embedding") else None
            d["corpus_ids"] = self.project_corpus_ids(d["id"])
            d["chats"] = self.con.execute("SELECT COUNT(*) FROM chats WHERE project_id=?", (d["id"],)).fetchone()[0]
            d["reviews"] = self.con.execute("SELECT COUNT(*) FROM reviews WHERE project_id=?",
                                            (d["id"],)).fetchone()[0]
            last = self.con.execute(
                "SELECT MAX(t) FROM (SELECT MAX(updated_at) AS t FROM chats WHERE project_id=?"
                " UNION ALL SELECT MAX(updated_at) FROM reviews WHERE project_id=?)", (d["id"], d["id"])).fetchone()[0]
            d["activity_at"] = max(x for x in (last, d["updated_at"], d["opened_at"]) if x is not None)
            out.append(d)
        return out

    def project(self, project_id: int) -> dict | None:
        return next((p for p in self.projects() if p["id"] == project_id), None)

    def create_project(self, name: str, description: str = "", color: str = "") -> int:
        now = time.time()
        with self.write() as con:
            pid = con.execute(
                "INSERT INTO projects(name, description, color, created_at, updated_at, opened_at) VALUES(?,?,?,?,?,?)",
                (name.strip(), description, color, now, now, now)).lastrowid
            if not color:  # Farbe fest speichern, damit sie bei Export und Import gleich bleibt
                con.execute("UPDATE projects SET color=? WHERE id=?", (PROJECT_COLORS[pid % len(PROJECT_COLORS)], pid))
            return pid

    def update_project(self, project_id: int, **values) -> None:
        cols, params = [], []
        for k in ("name", "description", "color", "opened_at"):
            if values.get(k) is not None:
                cols.append(f"{k}=?")
                params.append(values[k].strip() if k == "name" else values[k])
        if "embedding" in values:  # {} oder None = kein eigenes Modell
            cols.append("embedding=?")
            params.append(json.dumps(values["embedding"]) if values["embedding"] else None)
        if not cols:
            return
        if "opened_at" not in values:
            cols.append("updated_at=?")
            params.append(time.time())
        with self.write() as con:
            con.execute(f"UPDATE projects SET {', '.join(cols)} WHERE id=?", params + [project_id])

    def delete_project(self, project_id: int) -> None:
        """Löscht das Projekt mit seinen Chats und Forschungsständen. Korpora bleiben (ggf. ohne Projekt)."""
        with self.write() as con:
            for (cid,) in con.execute("SELECT id FROM chats WHERE project_id=?", (project_id,)).fetchall():
                con.execute("DELETE FROM chat_messages WHERE chat_id=?", (cid,))
            con.execute("DELETE FROM chats WHERE project_id=?", (project_id,))
            for (rid,) in con.execute("SELECT id FROM reviews WHERE project_id=?", (project_id,)).fetchall():
                con.execute("DELETE FROM review_docs WHERE review_id=?", (rid,))
                con.execute("DELETE FROM review_pages WHERE review_id=?", (rid,))
            con.execute("DELETE FROM reviews WHERE project_id=?", (project_id,))
            con.execute("DELETE FROM project_corpora WHERE project_id=?", (project_id,))
            con.execute("DELETE FROM searches WHERE project_id=?", (project_id,))
            con.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def set_project_order(self, project_ids: list[int]) -> None:
        """Reihenfolge von Hand (Ziehen in der Projektspalte); nicht genannte Projekte bleiben dahinter."""
        with self.write() as con:
            con.executemany("UPDATE projects SET position=? WHERE id=?",
                            [(i, int(pid)) for i, pid in enumerate(project_ids)])

    def set_project_archived(self, project_id: int, archived: bool) -> None:
        """Archivierte Projekte bleiben vollständig erhalten, erscheinen aber nur noch im Archiv."""
        with self.write() as con:
            con.execute("UPDATE projects SET archived_at=? WHERE id=?",
                        (time.time() if archived else None, project_id))

    # -- Suchverlauf (je Projekt) ---------------------------------------------------------------
    def searches(self, project_id: int) -> list[dict]:
        out = []
        for r in self.con.execute("SELECT * FROM searches WHERE project_id=? ORDER BY used_at DESC, id DESC",
                                  (project_id,)):
            d = dict(r)
            d["query"] = json.loads(d["query"] or "{}")
            del d["signature"]
            out.append(d)
        return out

    def remember_search(self, project_id: int, query: dict, sort: str, total: int,
                        used_at: float | None = None) -> int:
        """Suche in den Verlauf des Projekts; dieselbe Suche erneut ausgeführt rückt nur nach oben."""
        now = used_at or time.time()
        signature = json.dumps(query, ensure_ascii=False, sort_keys=True)
        with self.write() as con:
            con.execute(
                "INSERT INTO searches(project_id, signature, query, sort, total, created_at, used_at)"
                " VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id, signature)"
                " DO UPDATE SET sort=excluded.sort, total=excluded.total, used_at=excluded.used_at",
                (project_id, signature, json.dumps(query, ensure_ascii=False), sort, int(total), now, now))
            return con.execute("SELECT id FROM searches WHERE project_id=? AND signature=?",
                               (project_id, signature)).fetchone()[0]

    def forget_searches(self, project_id: int, search_id: int | None = None) -> None:
        """Eine Suche aus dem Verlauf entfernen oder (ohne ID) den ganzen Verlauf des Projekts."""
        with self.write() as con:
            if search_id is None:
                con.execute("DELETE FROM searches WHERE project_id=?", (project_id,))
            else:
                con.execute("DELETE FROM searches WHERE project_id=? AND id=?", (project_id, search_id))

    def project_corpus_ids(self, project_id: int) -> list[int]:
        return [r[0] for r in self.con.execute(
            "SELECT pc.corpus_id FROM project_corpora pc JOIN corpora c ON c.id = pc.corpus_id"
            " WHERE pc.project_id=? ORDER BY c.name COLLATE NOCASE", (project_id,))]

    def corpus_project_ids(self, corpus_id: int) -> list[int]:
        return [r[0] for r in self.con.execute(
            "SELECT project_id FROM project_corpora WHERE corpus_id=? ORDER BY project_id", (corpus_id,))]

    def assign_corpus(self, project_id: int, corpus_id: int, assigned: bool = True) -> None:
        with self.write() as con:
            if assigned:
                con.execute("INSERT OR IGNORE INTO project_corpora VALUES(?,?)", (project_id, corpus_id))
            else:
                con.execute("DELETE FROM project_corpora WHERE project_id=? AND corpus_id=?", (project_id, corpus_id))

    def adopt_orphans(self, project_id: int) -> None:
        """Chats, Forschungsstände und Korpora ohne Projekt diesem Projekt zuordnen."""
        with self.write() as con:
            con.execute("UPDATE chats SET project_id=? WHERE project_id IS NULL", (project_id,))
            con.execute("UPDATE reviews SET project_id=? WHERE project_id IS NULL", (project_id,))
            con.execute("INSERT OR IGNORE INTO project_corpora SELECT ?, id FROM corpora"
                        " WHERE id NOT IN (SELECT corpus_id FROM project_corpora)", (project_id,))

    # -- Chats -----------------------------------------------------------------------------
    def create_chat(self, title: str, project_id: int | None = None) -> int:
        now = time.time()
        with self.write() as con:
            return con.execute("INSERT INTO chats(title, created_at, updated_at, project_id) VALUES(?,?,?,?)",
                               (title, now, now, project_id)).lastrowid

    def add_chat_message(self, chat_id: int, role: str, content: str, sources=None, meta=None) -> int:
        now = time.time()
        with self.write() as con:
            con.execute("UPDATE chats SET updated_at=? WHERE id=?", (now, chat_id))
            return con.execute(
                "INSERT INTO chat_messages(chat_id, role, content, sources, meta, created_at) VALUES(?,?,?,?,?,?)",
                (chat_id, role, content, json.dumps(sources or [], ensure_ascii=False),
                 json.dumps(meta or {}, ensure_ascii=False), now),
            ).lastrowid

    def chats(self, limit: int = 200, project_id: int | None = None) -> list[dict]:
        if project_id is None:
            return [dict(r) for r in self.con.execute(
                "SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,))]
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM chats WHERE project_id=? ORDER BY updated_at DESC LIMIT ?", (project_id, limit))]

    def chat(self, chat_id: int) -> dict | None:
        row = self.con.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        return dict(row) if row else None

    def rename_chat(self, chat_id: int, title: str) -> None:
        with self.write() as con:
            con.execute("UPDATE chats SET title=? WHERE id=?", (title.strip(), chat_id))

    def chat_messages(self, chat_id: int) -> list[dict]:
        out = []
        for r in self.con.execute("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id", (chat_id,)):
            d = dict(r)
            d["sources"] = json.loads(d["sources"] or "[]")
            d["meta"] = json.loads(d["meta"] or "{}")
            out.append(d)
        return out

    def delete_chat(self, chat_id: int) -> None:
        with self.write() as con:
            con.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
            con.execute("DELETE FROM chats WHERE id=?", (chat_id,))

    # -- Auswertungsblätter --------------------------------------------------------------
    def get_sheet(self, lib: str, item_key: str) -> dict | None:
        row = self.con.execute("SELECT * FROM sheets WHERE lib=? AND item_key=?", (lib, item_key)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["sheet"] = json.loads(d["sheet"])
        return d

    def put_sheet(self, lib: str, item_key: str, sheet: dict, model: str, note_key: str | None = None) -> None:
        with self.write() as con:
            con.execute(
                "INSERT OR REPLACE INTO sheets VALUES(?,?,?,?,?,?)",
                (lib, item_key, json.dumps(sheet, ensure_ascii=False), model, note_key, time.time()),
            )

    def set_sheet_note(self, lib: str, item_key: str, note_key: str) -> None:
        with self.write() as con:
            con.execute("UPDATE sheets SET note_key=? WHERE lib=? AND item_key=?", (note_key, lib, item_key))

    def sheet_count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM sheets").fetchone()[0]

    # -- Wissenskorpora ------------------------------------------------------------------------
    # Ein Korpus ist eine benannte Auswahl von Quellen: "lib:KEY" (Sammlung inkl. Untersammlungen)
    # oder "lib:*" (ganze Bibliothek). Alle Korpora zusammen bestimmen, was indexiert wird.
    def corpora(self) -> list[dict]:
        out = []
        for r in self.con.execute("SELECT * FROM corpora ORDER BY name COLLATE NOCASE"):
            d = dict(r)
            d["sources"] = json.loads(d["sources"] or "[]")
            out.append(d)
        return out

    def corpus(self, corpus_id: int) -> dict | None:
        row = self.con.execute("SELECT * FROM corpora WHERE id=?", (corpus_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["sources"] = json.loads(d["sources"] or "[]")
        return d

    def create_corpus(self, name: str, sources: list[str], description: str = "") -> int:
        now = time.time()
        with self.write() as con:
            return con.execute(
                "INSERT INTO corpora(name, description, sources, created_at, updated_at) VALUES(?,?,?,?,?)",
                (name.strip(), description, json.dumps(sorted(set(sources))), now, now),
            ).lastrowid

    def update_corpus(self, corpus_id: int, **values) -> None:
        cols, params = [], []
        for k in ("name", "description", "sources"):
            if k in values and values[k] is not None:
                v = values[k]
                if k == "sources":
                    v = json.dumps(sorted(set(v)))
                elif k == "name":
                    v = v.strip()
                cols.append(f"{k}=?")
                params.append(v)
        if not cols:
            return
        cols.append("updated_at=?")
        params += [time.time(), corpus_id]
        with self.write() as con:
            con.execute(f"UPDATE corpora SET {', '.join(cols)} WHERE id=?", params)

    def delete_corpus(self, corpus_id: int) -> None:
        with self.write() as con:
            con.execute("DELETE FROM project_corpora WHERE corpus_id=?", (corpus_id,))
            con.execute("DELETE FROM corpora WHERE id=?", (corpus_id,))

    def missing_by_attachment(self, space: str | None) -> dict[tuple[str, str], int]:
        """Je Anhang (lib, att_key): Abschnitte ohne Vektor des Embedding-Raums (nur Anhänge mit Lücken)."""
        return {k: missing for k, (_, missing) in self.chunk_coverage(space).items() if missing}

    def chunk_coverage(self, space: str | None) -> dict[tuple[str, str], tuple[int, int]]:
        """Je Anhang (lib, att_key) mit Abschnitten: (Abschnitte, davon ohne Vektor des Embedding-Raums)."""
        if not space:
            return {}
        return {(r[0], r[1]): (r[2], r[3]) for r in self.con.execute(
            "SELECT c.lib, c.att_key, COUNT(*), SUM(e.chunk_id IS NULL) FROM chunks c"
            " LEFT JOIN embeddings e ON e.space=? AND e.chunk_id=c.id"
            " WHERE c.kind != 'references' AND c.att_key != '' GROUP BY c.lib, c.att_key", (space,))}

    @staticmethod
    def doc_state(status: str, coverage: tuple[int, int] | None, busy: bool = False) -> str:
        """Zustand eines Texts für das aktive Modell.

        indexed: gelesen und mit dem Modell durchsuchbar; to_embed: gelesen, Vektoren fehlen (z. B. nach einem
        Modellwechsel); refresh: wartet auf erneutes Lesen (genauere Seitenzahlen, geänderte Datei), ist mit dem
        bisherigen Text aber durchsuchbar; pending: noch nicht gelesen (oder gerade in Arbeit); no_text, error."""
        total, missing = coverage or (0, 0)
        if status == "indexed":
            if not missing:
                return "indexed"
            return "pending" if busy else "to_embed"
        if status == "pending":
            return "refresh" if total and not missing and not busy else "pending"
        return status

    def attachments_to_embed(self, space: str, scope: set[tuple[str, str]] | None) -> list[dict]:
        """Gelesene Texte, deren Abschnitte im Embedding-Raum noch fehlen (z. B. nach einem Modellwechsel)."""
        missing = self.missing_by_attachment(space)
        if not missing:
            return []
        out = []
        for r in self.con.execute("SELECT * FROM attachments WHERE status='indexed' ORDER BY lib, parent"):
            n = missing.get((r["lib"], r["key"]))
            if n and (scope is None or (r["lib"], r["parent"]) in scope):
                out.append({**dict(r), "missing": n})
        return out

    def abstracts_to_embed(self, space: str, scope: set[tuple[str, str]] | None) -> list[dict]:
        """Abstracts (Einträge ohne eigenen Anhang-Text) ohne Vektor im Embedding-Raum."""
        rows = self.con.execute(
            "SELECT c.* FROM chunks c LEFT JOIN embeddings e ON e.space=? AND e.chunk_id=c.id"
            " WHERE e.chunk_id IS NULL AND c.kind != 'references' AND c.att_key='' ORDER BY c.id", (space,))
        return [dict(r) for r in rows if scope is None or (r["lib"], r["item_key"]) in scope]

    def scope_stats(self, scope: set[tuple[str, str]] | None, space: str | None) -> dict:
        """Kennzahlen für eine Menge von Einträgen (z. B. einen Korpus).

        indexed: mit dem aktiven Embedding-Modell durchsuchbar (Text gelesen und alle Abschnitte eingebettet);
        to_embed: Text gelesen, für dieses Modell aber noch nicht (vollständig) eingebettet; refresh: wartet auf
        erneutes Lesen, ist aber mit dem bisherigen Text durchsuchbar (siehe doc_state); read: Text gelesen.
        to_embed_chunks: Abschnitte, die ein reiner Einbett-Lauf einbetten würde (fehlende der einzubettenden Texte
        und Abstracts) – anders als chunks_missing ohne die Abschnitte von Texten, die ohnehin neu gelesen werden."""
        if scope is not None and not scope:
            return {"items": 0, "documents": 0, "indexed": 0, "to_embed": 0, "refresh": 0, "read": 0, "pending": 0,
                    "no_text": 0, "error": 0, "chunks": 0, "embedded": 0, "chunks_missing": 0, "to_embed_chunks": 0,
                    "last_read_at": None}
        rows = self.con.execute("SELECT lib, key, parent, status, indexed_at FROM attachments"
                                " WHERE status NOT IN ('skipped','redundant')").fetchall()
        coverage = self.chunk_coverage(space)
        counts = {"indexed": 0, "to_embed": 0, "refresh": 0, "pending": 0, "no_text": 0, "error": 0}
        docs = read = to_embed_chunks = 0
        last_read = None  # wann zuletzt ein Text dieses Umfangs gelesen wurde
        for r in rows:
            if scope is None or (r["lib"], r["parent"]) in scope:
                docs += 1
                if r["status"] == "indexed" and r["indexed_at"] and (last_read is None or r["indexed_at"] > last_read):
                    last_read = r["indexed_at"]
                key = (r["lib"], r["key"])
                state = self.doc_state(r["status"], coverage.get(key), key == self.busy)
                read += r["status"] == "indexed" and state != "pending"
                if state == "to_embed":
                    to_embed_chunks += coverage[key][1]
                counts[state] = counts.get(state, 0) + 1
        items = len(scope) if scope is not None else self.con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        chunks = embedded = 0
        if space:
            q = ("SELECT c.lib, c.item_key, e.chunk_id IS NOT NULL AS emb, c.att_key FROM chunks c LEFT JOIN embeddings e"
                 " ON e.space=? AND e.chunk_id=c.id WHERE c.kind != 'references'")
            for r in self.con.execute(q, (space,)):
                if scope is None or (r["lib"], r["item_key"]) in scope:
                    chunks += 1
                    embedded += r["emb"]
                    to_embed_chunks += not r["emb"] and r["att_key"] == ""  # Abstracts bettet jeder Lauf ein
        return {"items": items, "documents": docs, **counts, "read": read, "chunks": chunks, "embedded": embedded,
                "chunks_missing": chunks - embedded if space else 0, "to_embed_chunks": to_embed_chunks,
                "last_read_at": last_read}

    # -- Forschungsstand-Projekte -----------------------------------------------------------
    def create_review(self, title: str, question: str, state: dict, project_id: int | None = None) -> int:
        now = time.time()
        with self.write() as con:
            return con.execute(
                "INSERT INTO reviews(title, question, state, created_at, updated_at, project_id) VALUES(?,?,?,?,?,?)",
                (title, question, json.dumps(state, ensure_ascii=False), now, now, project_id),
            ).lastrowid

    def update_review_title(self, review_id: int, title: str) -> None:
        with self.write() as con:
            con.execute("UPDATE reviews SET title=?, updated_at=? WHERE id=?", (title.strip(), time.time(), review_id))

    def get_review(self, review_id: int) -> dict | None:
        row = self.con.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["state"] = json.loads(d["state"] or "{}")
        return d

    def update_review_state(self, review_id: int, state: dict) -> None:
        with self.write() as con:
            con.execute("UPDATE reviews SET state=?, updated_at=? WHERE id=?",
                        (json.dumps(state, ensure_ascii=False), time.time(), review_id))

    def reviews(self, project_id: int | None = None) -> list[dict]:
        sql = "SELECT id, title, question, created_at, updated_at, project_id FROM reviews"
        if project_id is None:
            return [dict(r) for r in self.con.execute(sql + " ORDER BY updated_at DESC")]
        return [dict(r) for r in self.con.execute(sql + " WHERE project_id=? ORDER BY updated_at DESC", (project_id,))]

    def delete_review(self, review_id: int) -> None:
        with self.write() as con:
            con.execute("DELETE FROM review_docs WHERE review_id=?", (review_id,))
            con.execute("DELETE FROM review_pages WHERE review_id=?", (review_id,))
            con.execute("DELETE FROM reviews WHERE id=?", (review_id,))

    # Seite eines Belegs ohne Seitenangabe (für den Link ins PDF), je Forschungsstand und Belegstelle gemerkt
    def review_pages(self, review_id: int) -> dict[str, int | None]:
        return {r["ref"]: r["page"] for r in self.con.execute(
            "SELECT ref, page FROM review_pages WHERE review_id=?", (review_id,))}

    def put_review_pages(self, review_id: int, pages: dict[str, int | None]) -> None:
        if not pages:
            return
        with self.write() as con:
            con.executemany("INSERT OR REPLACE INTO review_pages VALUES(?,?,?)",
                            [(review_id, ref, page) for ref, page in pages.items()])

    def put_review_docs(self, review_id: int, docs: list[dict]) -> None:
        with self.write() as con:
            con.execute("DELETE FROM review_docs WHERE review_id=?", (review_id,))
            con.executemany(
                "INSERT INTO review_docs VALUES(?,?,?,?,?,?,?,?)",
                [(review_id, d["lib"], d["item_key"], d.get("score", 0), d.get("hits", 0), d.get("decision"),
                  d.get("reason"), 1 if d.get("included") else 0) for d in docs],
            )

    def review_docs(self, review_id: int) -> list[dict]:
        rows = self.con.execute(
            "SELECT * FROM review_docs WHERE review_id=? ORDER BY included DESC, score DESC", (review_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def set_review_doc_included(self, review_id: int, lib: str, item_key: str, included: bool) -> None:
        with self.write() as con:
            con.execute("UPDATE review_docs SET included=? WHERE review_id=? AND lib=? AND item_key=?",
                        (1 if included else 0, review_id, lib, item_key))


def _item_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("creators", "tags", "collections"):
        d[k] = json.loads(d[k] or "[]")
    d["data"] = json.loads(d.get("data") or "{}")
    return d
