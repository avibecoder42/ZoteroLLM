"""Test-Doubles der Recherche: Attrappe des Zotero-Ports, Schlüsselspeicher im Speicher, simulierte Quellen (PubMed,
OpenAlex, Crossref) als httpx.MockTransport. Kein Test braucht Netz."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from zotllm.research.http import Http
from zotllm.research.ports import MY_LIBRARY

# Echte Suchstrings eines Projekts (Ordner mit .txt-Dateien, nur gelesen) – optional, sonst werden die Tests übersprungen
QUERIES = Path(os.environ.get("ZOTLLM_TEST_QUERIES") or Path(__file__).parent / "queries-fehlen")


class MemoryKeyStore:
    def __init__(self, **values):
        self.values = {k.replace("_", "-"): v for k, v in values.items()}

    def get(self, name):
        return self.values.get(name)


class FakeZoteroPort:
    """Attrappe: hält Sammlungen und Einträge im Speicher und zählt jeden Schreibzugriff."""

    backend = "fake"

    def __init__(self, items=None, collections=None, writable=True):
        self.items = {it["key"]: it for it in (items or [])}
        self.cols = {c["key"]: dict(c) for c in (collections or [])}
        self.writable = writable
        self.writes = []
        self._n = 0

    def _key(self, prefix):
        self._n += 1
        return f"{prefix}{self._n:06d}"

    def status(self):
        return {"ok": True, "backend": self.backend, "message": "Attrappe"}

    def can_write(self, lib=MY_LIBRARY):
        return self.writable

    def libraries(self):
        return [{"lib": MY_LIBRARY, "name": "Meine Bibliothek"}, {"lib": "groups/4755508", "name": "Gruppe"}]

    def collections(self, lib):
        return [dict(c) for c in self.cols.values()]

    def iter_items(self, lib):
        yield from self.items.values()

    def create_collection(self, lib, name, parent=None):
        key = self._key("C")
        self.cols[key] = {"key": key, "name": name, "parent": parent}
        self.writes.append(("collection", lib, name, parent))
        return key

    def create_items(self, lib, items):
        out = []
        for it in items:
            key = self._key("I")
            self.items[key] = {"key": key, "version": 1, "data": dict(it, key=key)}
            out.append({"key": key})
        self.writes.append(("items", lib, len(items)))
        return out

    def add_to_collection(self, lib, collection_key, item_keys):
        n = 0
        for k in item_keys:
            cols = self.items[k]["data"].setdefault("collections", [])
            if collection_key not in cols:
                cols.append(collection_key)
                n += 1
        self.writes.append(("link", lib, collection_key, list(item_keys)))
        return n


# ------------------------------------------------------------------------------------------- simulierte Quellen
def pubmed_article(pmid, title, doi="", year="2021", abstract="An abstract about online aggression.", journal="J Youth"):
    doi_xml = f'<ArticleId IdType="doi">{doi}</ArticleId>' if doi else ""
    return f"""
<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
  <Journal><ISSN>1234-5678</ISSN><JournalIssue><Volume>12</Volume><Issue>3</Issue><PubDate><Year>{year}</Year><Month>Mar</Month></PubDate></JournalIssue>
  <Title>{journal}</Title><ISOAbbreviation>J Y</ISOAbbreviation></Journal>
  <ArticleTitle>{title}.</ArticleTitle><Pagination><MedlinePgn>1-10</MedlinePgn></Pagination>
  <Abstract><AbstractText Label="BACKGROUND">{abstract}</AbstractText></Abstract>
  <AuthorList><Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author><Author><LastName>Roe</LastName><ForeName>Max</ForeName></Author></AuthorList>
  <Language>eng</Language></Article>
  <MeshHeadingList><MeshHeading><DescriptorName>Adolescent</DescriptorName></MeshHeading></MeshHeadingList>
</MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pubmed">{pmid}</ArticleId>{doi_xml}</ArticleIdList></PubmedData></PubmedArticle>"""


def openalex_work(wid, title, doi="", year=2022, pmid="", abstract="Online conflict among teens", lang="en"):
    words = abstract.split()
    inv = {}
    for i, w in enumerate(words):
        inv.setdefault(w, []).append(i)
    return {
        "id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/{doi}" if doi else None, "display_name": title,
        "publication_year": year, "publication_date": f"{year}-05-01", "type": "article", "language": lang,
        "ids": {"openalex": f"https://openalex.org/{wid}", **({"pmid": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"} if pmid else {})},
        "authorships": [{"author": {"display_name": "Jane Doe"}}, {"author": {"display_name": "Ludwig van Beethoven"}}],
        "primary_location": {"source": {"display_name": "New Media & Society", "type": "journal", "issn_l": "1461-4448"}},
        "biblio": {"volume": "7", "issue": "2", "first_page": "100", "last_page": "120"},
        "abstract_inverted_index": inv, "cited_by_count": 5,
    }


class SourceSim:
    """Ein MockTransport für alle Quellen. Zählt Anfragen je Host; pubmed/openalex/crossref sind anpassbar."""

    def __init__(self):
        self.calls = []
        self.pubmed_articles = [pubmed_article("111", "Teasing online among adolescents", doi="10.1/abc"),
                                pubmed_article("222", "Bystanders in group chats", doi="10.1/def", year="2019")]
        self.pubmed_count = None
        self.openalex_works = [openalex_work("W1", "Teasing online among adolescents", doi="10.1/ABC", pmid="111"),
                               openalex_work("W2", "Digital stress and friendship conflict", doi="10.1/xyz")]
        self.openalex_count = None
        self.crossref = {"10.1/xyz": {"DOI": "10.1/xyz", "type": "journal-article", "title": ["Digital stress and friendship conflict"],
                                      "container-title": ["New Media & Society"], "volume": "7", "issue": "2", "page": "100-120",
                                      "author": [{"family": "Doe", "given": "Jane M."}, {"family": "van Beethoven", "given": "Ludwig"}],
                                      "issued": {"date-parts": [[2022, 5, 1]]}, "ISSN": ["1461-4448"]}}
        self.fail_once = set()
        self.s2_abstracts: dict[str, str] = {}   # DOI → Abstract für die Batch-Abfrage von Semantic Scholar
        self.s2_status = 200
        self.extra: dict[str, object] = {}       # host → Handler(request) für weitere Quellen

    def transport(self):
        return httpx.MockTransport(self.handle)

    def http(self):
        return Http(transport=self.transport(), sleep=lambda s: None)

    def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        self.calls.append((host, path, dict(request.url.params)))
        if (host, path) in self.fail_once:
            self.fail_once.discard((host, path))
            return httpx.Response(429, headers={"Retry-After": "0"})
        if host == "eutils.ncbi.nlm.nih.gov":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if path.endswith("esearch.fcgi") and "[doi]" in form.get("term", ""):
                wanted = {d.lower() for d in re.findall(r'"([^"]+)"\[doi\]', form["term"])}
                ids = [re.search(r"<PMID>(\d+)</PMID>", a).group(1) for a in self.pubmed_articles
                       if (m := re.search(r'IdType="doi">([^<]+)<', a)) and m.group(1).lower() in wanted]
                return httpx.Response(200, json={"esearchresult": {"count": str(len(ids)), "idlist": ids}})
            if path.endswith("efetch.fcgi") and "id" in form:
                ids = set(form["id"].split(","))
                arts = [a for a in self.pubmed_articles if re.search(r"<PMID>(\d+)</PMID>", a).group(1) in ids]
                return httpx.Response(200, content=("<PubmedArticleSet>" + "".join(arts) + "</PubmedArticleSet>").encode())
            if path.endswith("esearch.fcgi"):
                n = self.pubmed_count if self.pubmed_count is not None else len(self.pubmed_articles)
                return httpx.Response(200, json={"esearchresult": {
                    "count": str(n), "querytranslation": f"translated({form.get('term', '')})", "webenv": "WE", "querykey": "1",
                    "warninglist": {"phrasesignored": ["peace and quiet"]} if "peace and quiet" in form.get("term", "") else {}}})
            if path.endswith("efetch.fcgi"):
                start, n = int(form["retstart"]), int(form["retmax"])
                body = "<PubmedArticleSet>" + "".join(self.pubmed_articles[start:start + n]) + "</PubmedArticleSet>"
                return httpx.Response(200, content=body.encode())
        if host == "api.openalex.org":
            params = dict(request.url.params)
            count = self.openalex_count if self.openalex_count is not None else len(self.openalex_works)
            if params.get("select") == "id":
                return httpx.Response(200, json={"meta": {"count": count}, "results": []})
            per = int(params.get("per-page", 25))
            start = 0 if params.get("cursor") == "*" else int(params["cursor"])
            page = self.openalex_works[start:start + per]
            nxt = str(start + per) if start + per < len(self.openalex_works) else None
            return httpx.Response(200, json={"meta": {"count": count, "next_cursor": nxt}, "results": page})
        if host == "api.crossref.org":
            doi = path.split("/works/", 1)[1].lower()
            if doi in self.crossref:
                return httpx.Response(200, json={"message": self.crossref[doi]})
            return httpx.Response(404, text="Resource not found.")
        if host == "api.semanticscholar.org" and path.endswith("/paper/batch"):
            if self.s2_status != 200:
                return httpx.Response(self.s2_status, json={"message": "Too Many Requests"})
            ids = json.loads(request.content)["ids"]
            return httpx.Response(200, json=[{"abstract": self.s2_abstracts[i[4:].lower()]} if i[4:].lower() in self.s2_abstracts
                                             else None for i in ids])
        if host in self.extra:
            return self.extra[host](request)
        return httpx.Response(404, json={"error": f"unbekannt: {host}{path}"})


def json_body(request: httpx.Request):
    return json.loads(request.content or b"null")
