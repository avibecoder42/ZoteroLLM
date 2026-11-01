"""swisscovery (SLSP, Schweizer Hochschulbibliotheken): SRU-Schnittstelle des Netzwerk-Katalogs, Dublin Core.

CQL-Syntax (Ex Libris, Alma-SRU; Indexe in der Antwort auf ``operation=explain``): ``alma.all_for_ui="…"`` (alle
Felder, Phrase), ``alma.title all "…"`` (alle Wörter, beliebige Reihenfolge); and/or/not. Platzhalter ``*`` nur mit
``all``. Erscheinungsjahr: ``alma.main_pub_date>=2020``. Eine Seite liefert höchstens 50 Datensätze; SRU ist nicht für
Massenexporte gedacht. Metadaten frei nutzbar (SLSP, Open-Data-Strategie: https://slsp.ch/metadaten/).

Eigenheiten des Katalogs (geprüft am 30.10.2026), die die App abfängt:

- **Klammern:** Bei mehr als einem Klammerblock wertet er falsch aus – aus ``(A or B) and (C or D)`` wird
  ``A or (B and C) or D`` (175'817 statt höchstens 1'624 Treffer). Ein einzelner Klammerblock nach Begriffen geht
  (``Jahr and Begriff and (C or D)``). Darum zerlegt die App die zwei engsten Blöcke: je Begriff des engsten Blocks eine
  Abfrage „Begriff UND (zweitengster Block)“. Weitere Blöcke und das NOT prüft sie nach dem Abruf selbst (Titel,
  Schlagwörter, Beschreibung, Verlag). Die Trefferzahl ist die Summe je Begriff – eine Obergrenze.
- **Platzhalter** nur mit ``all`` (alle Wörter irgendwo). Einzelwörter mit * gehen so; Phrasen mit * würden dadurch sehr
  breit – die App sucht sie als Phrasen in gängigen Wortformen (assistive technology, assistive technologies).
- Treffer kommen nicht nach Relevanz, sondern etwa alphabetisch: Werden nicht alle abgerufen, ist der Ausschnitt zufällig.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable

from ..errors import SourceError
from ..http import Http
from . import SearchResult
from .pubmed import _lang

API = "https://swisscovery.slsp.ch/view/sru/41SLSP_NETWORK"
PLAN_TTL = 900  # Sekunden
MAX_SPLIT = 40  # höchstens so viele Teilabfragen für die zwei engsten Blöcke
_PLANS: dict[str, tuple[float, tuple]] = {}
NS = {"srw": "http://www.loc.gov/zing/srw/", "dc": "http://purl.org/dc/elements/1.1/",
      "diag": "http://www.loc.gov/zing/srw/diagnostic/"}
PAGE = 50
DEFAULT_MAX = 200
ISBN_RE = re.compile(r"\b(97[89][\d-]{10,14}|\d{9}[\dX])\b")


class Swisscovery:
    source = "swisscovery"

    def __init__(self, http: Http):
        self.http = http

    def _get(self, q: str, start: int, n: int) -> ET.Element:
        r = self.http.request("GET", API, params={"version": "1.2", "operation": "searchRetrieve", "recordSchema": "dc",
                                                  "query": q, "startRecord": start, "maximumRecords": n})
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as e:
            raise SourceError(f"swisscovery: Antwort nicht lesbar ({e})") from None
        diag = root.find(".//diag:message", NS)
        if diag is not None and root.findtext("srw:numberOfRecords", None, NS) is None:
            raise SourceError(f"swisscovery: {diag.text}")
        return root

    def _n(self, q: str) -> int:
        return int(self._get(q, 1, 0).findtext("srw:numberOfRecords", "0", NS) or 0)

    def _plan(self, q: str, limits: dict | None = None) -> tuple[str, int, list, list[str]]:
        """(Abfrage beim Katalog, ihre Trefferzahl, nachträglich zu prüfende Bedingungen, Hinweise). Kurz
        zwischengespeichert: Zählen und gleich danach Suchen fragt die Blöcke nicht zweimal ab."""
        years = _years(limits)
        key = f"{q}|{' and '.join(years)}"
        hit = _PLANS.get(key)
        if hit and time.monotonic() - hit[0] < PLAN_TTL:
            return hit[1]
        plan = self._make_plan(q, years)  # (Abfragen, Trefferzahl, nachträglich zu prüfen, Hinweise)
        _PLANS[key] = (time.monotonic(), plan)
        return plan

    def _counts(self, queries: list[str]) -> list[int]:
        with ThreadPoolExecutor(max_workers=min(4, len(queries))) as pool:  # gleichzeitig zählen
            return list(pool.map(self._n, queries))

    def _make_plan(self, q: str, years: list[str]) -> tuple[list[tuple[str, int]], int, list, list[str]]:
        def with_years(server: str) -> str:  # Jahresgrenze vor dem (einzigen) Klammerblock: das wertet der Katalog richtig aus
            return " and ".join(years + [f"({server})"]) if years else server

        def single(server: str, rest=(), notes=()):
            n = self._n(server)
            return [(server, n)], n, list(rest), list(notes)

        try:
            tree = parse_cql(q)
        except ValueError:
            return single(with_years(q))
        pos, neg = _conjunction(tree)
        if pos is None:  # ODER über Blöcke hinweg: so senden, wie es ist
            server = with_years(to_cql(tree))
            return single(server, notes=["swisscovery wertet verschachtelte Klammern nicht zuverlässig aus – Trefferzahl "
                                         "prüfen."] if server.count("(") > 1 else [])
        if len(pos) == 1:
            return single(with_years(flat_or(pos[0])), [("not_", g) for g in neg],
                          [f"Das NOT prüft die App nach dem Abruf; die Trefferzahl ist eine Obergrenze."] if neg else [])
        sizes = self._counts([with_years(flat_or(g)) for g in pos])
        order = sorted(range(len(pos)), key=lambda i: sizes[i])
        a, b = order[0], order[1]
        clauses = list(dict.fromkeys(c for t in _terms(pos[a]) for c in term_clauses(t)))
        rest = [pos[i] for i in order[2:]] + [("not_", g) for g in neg]
        if len(clauses) > MAX_SPLIT:  # zu viele Begriffe: nur der engste Block, der Rest nachträglich
            return single(with_years(flat_or(pos[a])), [pos[i] for i in order[1:]] + [("not_", g) for g in neg],
                          [f"swisscovery wertet mehrere Klammerblöcke nicht richtig aus: abgefragt wird der engste Block "
                           f"({sizes[a]} Treffer); die übrigen prüft die App nach dem Abruf. Die Trefferzahl ist eine Obergrenze."])
        queries = [" and ".join(years + [c, f"({flat_or(pos[b])})"]) for c in clauses]
        counts = self._counts(queries)
        n = sum(counts)
        note = (f"swisscovery wertet mehrere Klammerblöcke nicht richtig aus: die App fragt die zwei engsten Blöcke Begriff "
                f"für Begriff ab ({len(queries)} Abfragen) – bis zu {n} Treffer (Summe je Begriff, Überschneidungen doppelt)."
                + (f" {len(rest)} weitere Bedingung(en) prüft sie nach dem Abruf in Titel, Schlagwörtern, Beschreibung und "
                   "Verlag." if rest else ""))
        return [(qq, c) for qq, c in zip(queries, counts) if c], n, rest, [note]

    def count(self, q: str, limits: dict | None = None) -> SearchResult:
        queries, n, rest, notes = self._plan(q, limits)
        return SearchResult(n, warnings=notes, upper_bound=bool(rest) or len(queries) > 1)

    def search(self, q: str, limits: dict | None = None, max_records: int | None = None,
               progress: Callable[[int, int], None] | None = None) -> SearchResult:
        n_max = max_records or DEFAULT_MAX
        queries, count, rest, notes = self._plan(q, limits)
        jobs, planned = [], 0  # Seiten der Teilabfragen, bis die gewünschte Zahl erreicht ist
        for server, n in queries:
            for start in range(1, n + 1, PAGE):
                if planned >= n_max:
                    break
                jobs.append((server, start))
                planned += min(PAGE, n - start + 1)
        records, seen, done = [], set(), 0
        with ThreadPoolExecutor(max_workers=4) as pool:  # Seiten gleichzeitig, Reihenfolge bleibt
            for root in pool.map(lambda j: self._get(j[0], j[1], PAGE), jobs):
                for r in (to_rec(x) for x in root.findall(".//srw:record", NS)):
                    key = r and (r["accession"] or r["title"])
                    if r and key not in seen:  # ohne Doppelte aus mehreren Teilabfragen
                        seen.add(key)
                        records.append(r)
                done += 1
                if progress:
                    progress(min(len(records), n_max), min(count, n_max))
        records = records[:n_max]
        fetched = len(records)
        if rest:  # die übrigen Blöcke und das NOT nachträglich
            records = [r for r in records if all(matches(c, r) for c in rest)]
            notes = notes + [f"Von {fetched} abgerufenen passen {len(records)} zu allen Blöcken."]
        y1, y2 = (limits or {}).get("year_from"), (limits or {}).get("year_to")
        if y1 or y2:  # zur Sicherheit auch nachträglich (Erscheinungsjahr laut Dublin Core)
            records = [r for r in records if not r["year"] or ((not y1 or r["year"] >= y1) and (not y2 or r["year"] <= y2))]
        warnings = notes + ([f"Bis zu {count} Treffer, abgerufen wurden {fetched} (ohne Doppelte)."] if count > fetched else [])
        return SearchResult(count, records[:n_max], warnings=warnings)


def _years(limits: dict | None) -> list[str]:
    """Jahresgrenze als Bedingung im Katalog (Erscheinungsjahr)."""
    y1, y2 = (limits or {}).get("year_from"), (limits or {}).get("year_to")
    return ([f"alma.main_pub_date>={int(y1)}"] if y1 else []) + ([f"alma.main_pub_date<={int(y2)}"] if y2 else [])


# ------------------------------------------------------------------------------------------- CQL selbst auswerten
CQL_TOKEN = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+)')
BOOL = ("and", "or", "not")
DEFAULT_INDEX = "alma.all_for_ui"


def parse_cql(q: str) -> tuple:
    """CQL wie spezifiziert: and/or/not gleichrangig, von links, Klammern.
    Knoten: ("term", index, wert, relation), (op, a, b)."""
    toks = [t for t in CQL_TOKEN.findall(q or "") if t]
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def clause():
        t = take() if peek() is not None else None
        if t is None:
            raise ValueError("leer")
        if t == "(":
            e = expr()
            if peek() != ")":
                raise ValueError("Klammer fehlt")
            take()
            return e
        m = re.match(r"^([\w.]+)(==|<>|>=|<=|=|>|<)$", t)
        if m:  # index="wert" (ohne Leerzeichen)
            return ("term", m.group(1).lower(), _unquote(take()), m.group(2))
        if peek() is not None and peek().lower() in ("=", "==", "all", "any", "adj", ">=", "<="):
            rel = take().lower()
            return ("term", t.lower(), _unquote(take()), rel)
        return ("term", DEFAULT_INDEX, _unquote(t), "=")

    def expr():
        node = clause()
        while peek() is not None and peek().lower() in BOOL:
            op = take().lower()
            node = (op, node, clause())
        return node

    tree = expr()
    if peek() is not None:
        raise ValueError("Rest nicht lesbar")
    return tree


def _unquote(t: str) -> str:
    return t[1:-1].replace('\\"', '"') if t.startswith('"') and t.endswith('"') else t


def _conjunction(node: tuple) -> tuple[list | None, list]:
    """Oberste Ebene als UND-Kette: (Blöcke, NOT-Blöcke); None, wenn oben ein ODER über Blöcke steht."""
    if node[0] == "and":
        a, na = _conjunction(node[1])
        b, nb = _conjunction(node[2])
        return (None, []) if a is None or b is None else (a + b, na + nb)
    if node[0] == "not":
        a, na = _conjunction(node[1])
        return (None, []) if a is None else (a, na + [node[2]])
    if node[0] == "or" and _has_and(node):
        return None, []
    return [node], []


def _has_and(node: tuple) -> bool:
    return node[0] in ("and", "not") or (node[0] == "or" and (_has_and(node[1]) or _has_and(node[2])))


def _terms(node: tuple) -> list[tuple]:
    return [node] if node[0] == "term" else _terms(node[1]) + _terms(node[2])


def term_clauses(node: tuple) -> list[str]:
    """Ein Suchbegriff als eine oder mehrere Bedingungen (ODER): Phrase mit ``=``; Einzelwort mit * über ``all`` (nur
    damit kennt der Katalog ``*``); Phrase mit * als Phrasen in gängigen Wortformen (``all`` wäre „alle Wörter irgendwo“)."""
    _, index, value, rel = node
    if "*" in value and " " in value.strip() and rel != "all":
        return [f'{index}="{v}"' for v in phrase_forms(value)]
    if "*" in value or rel == "all":
        return [f'{index} all "{value}"']
    return [f'{index}{rel}"{value}"']


def term_cql(node: tuple) -> str:
    c = term_clauses(node)
    return c[0] if len(c) == 1 else f"({' or '.join(c)})"


def to_cql(node: tuple) -> str:
    if node[0] == "term":
        return term_cql(node)
    left, right = to_cql(node[1]), to_cql(node[2])
    wrap = lambda n, x: x if n[0] == "term" else f"({x})"  # noqa: E731
    return f"{wrap(node[1], left)} {node[0]} {wrap(node[2], right)}"


def flat_or(node: tuple) -> str:
    """Ein ODER-Block als flache Kette ohne Klammern – die wertet der Katalog richtig aus."""
    return " or ".join(dict.fromkeys(c for t in _terms(node) for c in term_clauses(t)))


# Gängige Wortformen für Phrasen mit Platzhalter (Englisch, etwas Deutsch); das genaue Wortende prüft matches()
SUFFIX_FORMS = [("olog", ["ology", "ologies"]), ("cen", ["cent", "cents", "cence"]), ("it", ["ity", "ities"]),
                ("at", ["ation", "ational"]), ("i", ["ion", "ive"]), ("ic", ["ic", "ics", "ical"])]
COMMON_STEMS = {"child": ["child", "children"], "teen": ["teen", "teens", "teenager", "teenagers"],
                "parent": ["parent", "parents", "parental"], "bully": ["bully", "bullying", "bullied"],
                "bull": ["bully", "bullying", "bullied"], "universit": ["university", "universities"]}


def _forms(stem: str) -> list[str]:
    if stem.lower() in COMMON_STEMS:
        return COMMON_STEMS[stem.lower()]
    for end, forms in SUFFIX_FORMS:
        if stem.lower().endswith(end) and len(stem) > len(end) + 2:
            return [stem[: -len(end)] + f for f in forms]
    return [stem, stem + "s"]


def phrase_forms(value: str) -> list[str]:
    out = [""]
    for w in value.split():
        alts = _forms(w.rstrip("*")) if w.endswith("*") else [w.replace("*", "")]
        out = [f"{o} {a}".strip() for o in out for a in alts][:6]
    return out


def _regex(value: str, rel: str = "=") -> re.Pattern:
    """Nachträglicher Abgleich: Phrase (``=``) oder alle Wörter in beliebiger Reihenfolge (``all``); * = Wortende offen."""
    words = [w for w in value.split() if w]
    parts = [re.escape(w.rstrip("*")) + (r"\w*" if w.endswith("*") else r"(?:s|es|e|en)?") for w in words]
    if rel == "all":
        return re.compile(r"\A" + "".join(rf"(?=.*?\b{p}\b)" for p in parts), re.I | re.S)  # \A: nur ab Textanfang prüfen
    return re.compile(r"\b" + r"[\W_]+".join(parts) + r"\b", re.I)


def _text(rec: dict, index: str) -> str:
    if index == "alma.title":
        return rec.get("title") or ""
    if index == "alma.subjects":
        return " ".join(rec.get("subjects") or [])
    if index == "alma.description":
        return rec.get("abstract") or ""
    return " ".join([rec.get("title") or "", " ".join(rec.get("subjects") or []), rec.get("abstract") or "",
                     rec.get("publisher") or ""])


def matches(cond: tuple, rec: dict) -> bool:
    if cond[0] == "not_":
        return not matches(cond[1], rec)
    if cond[0] == "term":
        return bool(_regex(cond[2], cond[3]).search(_text(rec, cond[1])))
    if cond[0] == "and":
        return matches(cond[1], rec) and matches(cond[2], rec)
    if cond[0] == "or":
        return matches(cond[1], rec) or matches(cond[2], rec)
    return matches(cond[1], rec) and not matches(cond[2], rec)  # not


def _name(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.rstrip(".").split(",")]
    if len(parts) >= 2 and parts[1] and not parts[1].endswith(("company", "speaker", "editor", "author")):
        return [parts[0], parts[1]]
    return ["", parts[0]]


def to_rec(rec: ET.Element) -> dict | None:
    dc = rec.find(".//srw:recordData/*", NS)
    if dc is None:
        return None

    def vals(tag):
        return [re.sub(r"\s+", " ", e.text or "").strip() for e in dc.findall(f"dc:{tag}", NS) if (e.text or "").strip()]

    title = (vals("title") or [""])[0].rstrip(" /:").strip()
    date = (vals("date") or [""])[0]
    year = re.search(r"\d{4}", date)
    types = " ".join(vals("type")).lower()
    itype = "thesis" if "thesis" in types else "book"
    ident = vals("identifier")
    mms = rec.findtext("srw:recordIdentifier", "", NS)
    isbn = next((m.group(1) for i in ident for m in [ISBN_RE.search(i)] if m and "ISBN" in i.upper()), "")
    people = [p for p in vals("creator") + vals("contributor") if "company" not in p.lower()]
    return {
        "type": itype,
        "title": title,
        "authors": [_name(p) for p in vals("creator") if "company" not in p.lower()] or [_name(p) for p in people[:3]],
        "date": date,
        "year": int(year.group(0)) if year else None,
        "publisher": (vals("publisher") or [""])[0],
        "isbn": isbn,
        "abstract": " ".join(vals("description")),
        "lang": _lang((vals("language") or [""])[0]),
        "subjects": [s.rstrip(".") for s in vals("subject")],
        "accession": f"swisscovery:{mms}" if mms else "",
        "url": (f"https://swisscovery.slsp.ch/discovery/fulldisplay?docid=alma{mms}&vid=41SLSP_NETWORK:VU1_UNION"
                if mms else ""),
    }
