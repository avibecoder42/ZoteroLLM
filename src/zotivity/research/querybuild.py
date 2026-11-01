"""Konzeptblöcke → Suchstrings je Quelle, und PubMed-Strings → OpenAlex.

Ein Block ist ein dict: name, kind ("include" | "exclude"), field ("tiab" | "ti"), terms [..], mesh [..],
psycinfo [..] (PsycInfo-Schlagwörter für Ovid). Innerhalb eines Blocks gilt ODER, zwischen Blöcken UND; Ausschluss-
blöcke werden mit NOT angehängt. Übersetzungsentscheide wie in queries/LIESMICH.md:

| PubMed | Ovid PsycInfo | Web of Science | OpenAlex |
|---|---|---|---|
| ``[tiab]`` | ``.ti,ab,id.`` | ``TS=`` | ``title_and_abstract.search`` |
| ``[ti]`` | ``.ti.`` | ``TI=`` | (Titel und Abstract) |
| ``[Mesh]`` | ``exp …/`` (eigene Liste) | – | – |
"""

from __future__ import annotations

import re

TAGGED = re.compile(r"\[[A-Za-z][A-Za-z ]*(?::[A-Za-z]+)?\]\s*$")
FIELD_TAG = re.compile(r"\[([A-Za-z][A-Za-z ]*)(?::[A-Za-z]+)?\]")
MESH_TAGS = {"mesh", "mh", "majr", "mesh terms", "mesh major topic", "sh"}


def clean_terms(terms) -> list[str]:
    if isinstance(terms, str):
        terms = terms.splitlines()
    out = []
    for t in terms or []:
        t = t.strip().strip(",;").strip()
        if t and t not in out:
            out.append(t)
    return out


def _needs_quotes(term: str) -> bool:
    return bool(re.search(r"[^\w*]", term))


def _bare(term: str) -> str:
    return term.strip().strip('"').strip()


def _pubmed_term(term: str, tag: str) -> str:
    if TAGGED.search(term):  # schon mit Feld, z. B. "Internet Addiction Disorder"[Mesh]
        return term
    t = _bare(term)
    return f'"{t}"[{tag}]' if _needs_quotes(t) else f"{t}[{tag}]"


def _group(parts: list[str], op: str) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else "(" + f" {op} ".join(parts) + ")"


def _split(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    usable = [b for b in blocks if clean_terms(b.get("terms")) or clean_terms(b.get("mesh"))
              or clean_terms(b.get("psycinfo"))]
    return [b for b in usable if b.get("kind") != "exclude"], [b for b in usable if b.get("kind") == "exclude"]


def build_pubmed(blocks: list[dict]) -> dict:
    inc, exc = _split(blocks)
    notes = []

    def block(b):
        tag = "ti" if b.get("field") == "ti" else "tiab"
        parts = [_pubmed_term(t, tag) for t in clean_terms(b.get("terms"))]
        parts += [f'"{_bare(m)}"[Mesh]' for m in clean_terms(b.get("mesh"))]
        return _group(parts, "OR")

    s = " AND ".join(block(b) for b in inc if block(b))
    excl = [block(b) for b in exc if block(b)]
    if excl:
        s = f"{s} NOT {_group(excl, 'OR')}" if s else ""
        if not s:
            notes.append("Nur Ausschlussblöcke – es fehlt ein Block, der etwas einschliesst.")
    return {"source": "pubmed", "string": s, "notes": notes}


def _oa_term(term: str, notes: set) -> str:
    t = FIELD_TAG.sub("", _bare(term)).strip().strip('"')
    if "*" in t:
        notes.add("OpenAlex kennt keine Platzhalter (*): entfernt. OpenAlex sucht mit Wortstämmen, "
                  "ggf. Wortformen ergänzen (z. B. adolescent, adolescents, adolescence).")
        t = t.replace("*", "")
    return f'"{t}"' if re.search(r"[^\w]", t) else t


def build_openalex(blocks: list[dict]) -> dict:
    inc, exc = _split(blocks)
    notes: set[str] = set()
    if any(clean_terms(b.get("mesh")) for b in blocks):
        notes.add("MeSH-Schlagwörter gibt es in OpenAlex nicht – nur die Freitextbegriffe werden verwendet.")
    if any(b.get("field") == "ti" for b in blocks):
        notes.add("OpenAlex sucht hier in Titel und Abstract; Einschränkungen auf den Titel gelten nicht. "
                  "Ausschlüsse nur im Titel lassen sich im Pool als Vorfilter setzen.")

    def block(b):
        return _group([_oa_term(t, notes) for t in clean_terms(b.get("terms"))], "OR")

    s = " AND ".join(x for x in (block(b) for b in inc) if x)
    excl = [x for x in (block(b) for b in exc) if x]
    if excl and s:
        s = f"{s} NOT {_group(excl, 'OR')}"
    return {"source": "openalex", "string": s, "notes": sorted(notes)}


def _ovid_term(term: str) -> str:
    t = FIELD_TAG.sub("", _bare(term)).strip()
    return f'"{t}"' if " " in t and "*" not in t else t  # Ovid: benachbarte Wörter gelten ohnehin als Phrase


def build_ovid(blocks: list[dict]) -> dict:
    inc, exc = _split(blocks)
    lines, inc_n, exc_n = [], [], []
    for group, numbers in ((inc, inc_n), (exc, exc_n)):
        for b in group:
            suffix = ".ti." if b.get("field") == "ti" else ".ti,ab,id."
            terms = [_ovid_term(t) for t in clean_terms(b.get("terms"))]
            parts = []
            if terms:
                parts.append(f"({' or '.join(terms)}){suffix}" if len(terms) > 1 else f"{terms[0]}{suffix}")
            parts += [f"exp {_bare(h).rstrip('/')}/" for h in clean_terms(b.get("psycinfo"))]
            lines.append(" or ".join(parts))
            numbers.append(len(lines))
    if len(lines) > 1 and inc_n:
        combo = " and ".join(map(str, inc_n))
        if exc_n:
            combo += " not " + (" or ".join(map(str, exc_n)) if len(exc_n) == 1 else f"({' or '.join(map(str, exc_n))})")
        lines.append(combo)
    notes = ["Jede Zeile einzeln in Advanced Search eingeben (Keyword-Modus, „Map Term to Subject Heading“ aus); "
             "die letzte Zeile kombiniert sie."] if lines else []
    return {"source": "psycinfo", "string": "\n".join(lines), "lines": lines, "notes": notes}


def build_wos(blocks: list[dict]) -> dict:
    inc, exc = _split(blocks)

    def block(b):
        terms = [_ovid_term(t) for t in clean_terms(b.get("terms"))]
        if not terms:
            return ""
        tag = "TI" if b.get("field") == "ti" else "TS"
        return f"{tag}=({' OR '.join(terms)})"

    s = " AND ".join(x for x in (block(b) for b in inc) if x)
    excl = [x for x in (block(b) for b in exc) if x]
    if excl and s:
        s += " NOT " + (excl[0] if len(excl) == 1 else "(" + " OR ".join(excl) + ")")
    notes = ["Web of Science Core Collection, Advanced Search."] if s else []
    if any(clean_terms(b.get("mesh")) for b in blocks):
        notes.append("MeSH-Schlagwörter fehlen in WoS – Freitext ergänzen, falls nötig.")
    return {"source": "wos", "string": s, "notes": notes}


BUILDERS = {"pubmed": build_pubmed, "openalex": build_openalex, "psycinfo": build_ovid, "wos": build_wos}


def build(source: str, blocks: list[dict]) -> dict:
    if source not in BUILDERS:
        raise ValueError(f"Unbekannte Quelle: {source}")
    return BUILDERS[source](blocks)


CLASSIC = ("pubmed", "openalex", "psycinfo", "wos")


def build_all(blocks: list[dict], sources: list[str] | None = None) -> dict[str, dict]:
    """Suchstrings für die klassischen vier Quellen und die gewählten weiteren."""
    wanted = list(CLASSIC) + [s for s in sources or [] if s in BUILDERS and s not in CLASSIC]
    return {src: BUILDERS[src](blocks) for src in wanted}


# ------------------------------------------------------------------------------------------- PubMed → OpenAlex
TOKEN = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')


def pubmed_to_openalex(query: str) -> dict:
    """Feldkürzel entfernen, Platzhalter streichen, Begriffe mit Bindestrich in Anführungszeichen setzen."""
    notes = []
    tags = {m.group(1).lower() for m in FIELD_TAG.finditer(query)}
    if tags & MESH_TAGS:
        notes.append("MeSH-Schlagwörter sind als Freitext übernommen – OpenAlex kennt keine MeSH.")
    if "ti" in tags:
        notes.append("Einschränkungen auf den Titel ([ti]) gelten in OpenAlex für Titel und Abstract. "
                     "Ein Ausschluss nur im Titel lässt sich im Pool als Vorfilter setzen.")
    s = FIELD_TAG.sub("", query)
    wild = sorted({w for w in re.findall(r"[\w-]+\*", s)})
    if wild:
        shown = ", ".join(wild[:8]) + (" …" if len(wild) > 8 else "")
        notes.append(f"Platzhalter entfernt ({shown}). OpenAlex sucht mit Wortstämmen; "
                     "Wortformen wie „teenagers“ zu „teen*“ ggf. ergänzen.")
    s = s.replace("*", "").replace(",", " ")
    out = []
    for tok in TOKEN.findall(s):
        if tok.startswith('"') or tok in ("(", ")", "AND", "OR", "NOT"):
            out.append(tok)
        elif re.search(r"[^\w]", tok):
            out.append(f'"{tok}"')
        else:
            out.append(tok)
    s = " ".join(out).replace("( ", "(").replace(" )", ")")
    s = re.sub(r'""', '', s)
    return {"source": "openalex", "string": re.sub(r"\s+", " ", s).strip(), "notes": notes}


# ------------------------------------------------------------------------------------------- weitere Quellen
# PubMed-Strings werden in einen kleinen Baum zerlegt (PubMed liest von links nach rechts, Klammern gruppieren,
# Leerzeichen heisst UND) und je Zielquelle neu geschrieben. Konzeptblöcke ergeben denselben Baum.

OPS = ("AND", "OR", "NOT")
PM_TOKEN = re.compile(r'"[^"]*"(?:\[[^\]]*\])?|\(|\)|[^\s()"]+(?:\[[^\]]*\])?')
SOURCE_NAMES = {"europepmc": "Europe PMC", "eric": "ERIC", "econbiz": "EconBiz", "semanticscholar": "Semantic Scholar",
                "arxiv": "arXiv", "swisscovery": "swisscovery", "osf": "OSF"}


def _split_tag(tok: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)(?:\[([^\]]*)\])?$", tok, re.S)
    value, tag = m.group(1).strip(), (m.group(2) or "").split(":")[0].strip().lower()
    if tag in ("ti", "title"):
        return value, "ti"
    if tag in MESH_TAGS:
        return value, "mesh"
    return value, "tiab"


def parse_pubmed(query: str) -> tuple:
    toks = PM_TOKEN.findall(query or "")
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        pos[0] += 1
        return toks[pos[0] - 1]

    def atom():
        t = take()
        if t == "(":
            e = expr()
            if peek() == ")":
                take()
            return ("group", e)
        return ("term", *_split_tag(t))

    def expr():
        if peek() in (None, ")"):
            return ("term", "", "tiab")
        node = atom()
        while peek() not in (None, ")"):
            op = take().lower() if peek().upper() in OPS else "and"
            if peek() in (None, ")"):
                break
            node = (op, node, atom())
        return node

    return expr()


def _or_chain(nodes: list[tuple]) -> tuple | None:
    node = None
    for n in nodes:
        node = n if node is None else ("or", node, n)
    return node


def blocks_ast(blocks: list[dict]) -> tuple | None:
    inc, exc = _split(blocks)

    def group(b):
        f = "ti" if b.get("field") == "ti" else "tiab"
        terms = [("term", t, f) for t in clean_terms(b.get("terms"))]
        terms += [("term", m, "mesh") for m in clean_terms(b.get("mesh"))]
        chain = _or_chain(terms)
        return ("group", chain) if chain else None

    node = None
    for b in inc:
        g = group(b)
        if g:
            node = g if node is None else ("and", node, g)
    excl = _or_chain([g[1] for g in (group(b) for b in exc) if g])
    if node and excl:
        node = ("not", node, ("group", excl))
    return node


class Target:
    """Schreibweise einer Zielquelle. ``field`` setzt das Feld (tiab, ti, mesh) um einen Begriff."""

    source = ""
    AND, OR, NOT = " AND ", " OR ", " NOT "
    wildcards = True       # * am Wortende erlaubt (nicht in Phrasen)
    quote_all = False      # jeden Begriff in Anführungszeichen (CQL)
    mesh = False           # kennt MeSH als Feld

    def field(self, t: str, f: str, notes: set) -> str:
        return t

    def term(self, raw: str, f: str, notes: set) -> str:
        quoted = raw.strip().startswith('"')
        bare = raw.strip().strip('"').strip()
        if not bare:
            return ""
        if "*" in bare and (not self.wildcards or quoted or " " in bare):
            notes.add(f"{SOURCE_NAMES.get(self.source, self.source)}: Platzhalter (*) hier nicht möglich – entfernt; "
                      "Wortformen ggf. ausschreiben.")
            bare = bare.replace("*", "")
        if f == "mesh" and not self.mesh:
            notes.add("MeSH-Schlagwörter sind als Freitext übernommen.")
            f = "tiab"
        phrase = bool(re.search(r"[^\w*]", bare))
        t = f'"{bare}"' if phrase or self.quote_all or f == "mesh" else bare
        return self.field(t, f, notes)

    def negate(self, left: str, node: tuple, right: str, notes: set) -> str:
        return f"{left}{self.NOT}{right}"


class EuropePMCTarget(Target):
    source = "europepmc"
    mesh = True

    def field(self, t, f, notes):
        if f == "mesh":
            return f"MESH:{t}"
        return f"TITLE:{t}" if f == "ti" else f"(TITLE:{t} OR ABSTRACT:{t})"


class ERICTarget(Target):
    source = "eric"

    def field(self, t, f, notes):
        return f"title:{t}" if f == "ti" else f"(title:{t} OR description:{t})"


class EconBizTarget(Target):
    source = "econbiz"

    def field(self, t, f, notes):
        return f"title:{t}" if f == "ti" else t


def _leaves_if_or_chain(node: tuple) -> list[tuple[str, str]] | None:
    if node[0] == "term":
        return [(node[1], node[2])]
    if node[0] == "group":
        return _leaves_if_or_chain(node[1])
    if node[0] == "or":
        a, b = _leaves_if_or_chain(node[1]), _leaves_if_or_chain(node[2])
        return a + b if a is not None and b is not None else None
    return None


class SemanticScholarTarget(Target):
    source = "semanticscholar"
    AND, OR = " + ", " | "

    def field(self, t, f, notes):
        if f == "ti":
            notes.add("Semantic Scholar sucht immer in Titel und Abstract; „nur Titel“ gilt hier nicht.")
        return t

    def negate(self, left, node, right, notes):
        leaves = _leaves_if_or_chain(node)
        if leaves is not None:  # NICHT (a ODER b) = -a UND -b
            return left + "".join(f" + -{self.term(v, f, notes)}" for v, f in leaves)
        notes.add("Semantic Scholar: NICHT vor einer verschachtelten Klammer – bitte prüfen.")
        return f"{left} + -{right}"


class ArxivTarget(Target):
    source = "arxiv"
    NOT = " ANDNOT "
    wildcards = False

    def field(self, t, f, notes):
        return f"ti:{t}" if f == "ti" else f"(ti:{t} OR abs:{t})"


class SwisscoveryTarget(Target):
    """Platzhalter kennt der Katalog nur mit ``all`` (alle Wörter, beliebige Reihenfolge); Phrasen ohne Platzhalter mit
    ``=``. Mehrere Klammerblöcke wertet er falsch aus – das fängt die Quelle ab (sources/swisscovery.py)."""
    source = "swisscovery"
    AND, OR, NOT = " and ", " or ", " not "
    quote_all = True

    def term(self, raw, f, notes):
        bare = raw.strip().strip('"').strip()
        if not bare:
            return ""
        if f == "mesh":
            notes.add("MeSH-Schlagwörter sind als Freitext übernommen.")
            f = "tiab"
        index = "alma.title" if f == "ti" else "alma.all_for_ui"
        if "*" in bare and " " not in bare:
            return f'{index} all "{bare}"'
        if "*" in bare:
            notes.add("swisscovery: Phrasen mit Platzhalter sucht die App in gängigen Wortformen (assistive technolog* → "
                      "assistive technology, assistive technologies).")
        return f'{index}="{bare}"'


def emit(node: tuple | None, tgt: Target, notes: set) -> str:
    if node is None:
        return ""
    kind = node[0]
    if kind == "term":
        return tgt.term(node[1], node[2], notes)
    if kind == "group":
        inner = emit(node[1], tgt, notes)
        return inner if node[1][0] == "term" or not inner else f"({inner})"
    op, left_node, right_node = node
    left, right = emit(left_node, tgt, notes), emit(right_node, tgt, notes)
    if not left:
        return "" if op == "not" else right
    if not right:
        return left
    if op == "not":
        return tgt.negate(left, right_node, right, notes)
    return left + (tgt.AND if op == "and" else tgt.OR) + right


def _osf_keywords(node: tuple | None, notes: set) -> str:
    """OSF kennt kein ODER: je UND-Teil der erste Begriff (ohne NICHT-Teile)."""
    if node is None:
        return ""
    parts: list[tuple] = []

    def and_parts(n):
        if n[0] == "and":
            and_parts(n[1])
            and_parts(n[2])
        elif n[0] == "not":
            and_parts(n[1])
        else:
            parts.append(n)

    def first_term(n):
        while n[0] != "term":
            n = n[1]
        return n

    and_parts(node)
    words = []
    for p in parts:
        bare = first_term(p)[1].strip().strip('"').replace("*", "")
        if bare:
            words.append(f'"{bare}"' if " " in bare else bare)
    notes.add("OSF sucht einfach: alle Stichwörter müssen vorkommen, ODER und NICHT gehen nicht. Übernommen ist je "
              "Block der erste Begriff – für weitere Varianten eigene Suchstrings anlegen.")
    return " ".join(words)


TARGETS = {t.source: t() for t in (EuropePMCTarget, ERICTarget, EconBizTarget, SemanticScholarTarget, ArxivTarget,
                                     SwisscoveryTarget)}
TRANSLATABLE = ("openalex", *TARGETS, "osf")


def translate(query: str, to: str) -> dict:
    """PubMed-String → Zielquelle."""
    if to == "openalex":
        return pubmed_to_openalex(query)
    notes: set[str] = set()
    tree = parse_pubmed(query)
    if to == "osf":
        return {"source": to, "string": _osf_keywords(tree, notes), "notes": sorted(notes)}
    if to not in TARGETS:
        raise ValueError(f"Übersetzen nach {to} ist nicht vorgesehen.")
    return {"source": to, "string": emit(tree, TARGETS[to], notes).strip(), "notes": sorted(notes)}


def build_target(source: str, blocks: list[dict]) -> dict:
    notes: set[str] = set()
    tree = blocks_ast(blocks)
    if source == "osf":
        s = _osf_keywords(tree, notes) if tree else ""
        return {"source": source, "string": s, "notes": sorted(notes) if s else []}
    return {"source": source, "string": emit(tree, TARGETS[source], notes).strip(), "notes": sorted(notes)}


for _src in (*TARGETS, "osf"):
    BUILDERS[_src] = (lambda s: lambda blocks: build_target(s, blocks))(_src)
