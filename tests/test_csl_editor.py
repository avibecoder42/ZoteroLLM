"""CSL-Editor: Suche in der Stilsammlung (sparsam geladen), eigene Stile, Vorversionen, Installation in Zotero."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from zotivity import csl_editor as csl
from zotivity.server.app import create_app

H = {"X-Zotivity": "1"}

STYLE = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0" demote-non-dropping-particle="never">
  <!-- Kommentar bleibt erhalten -->
  <info>
    <title>Muster-Stil</title>
    <title-short>MS</title-short>
    <id>http://www.zotero.org/styles/muster-stil</id>
    <link href="http://www.zotero.org/styles/muster-stil" rel="self"/>
    <category citation-format="author-date"/>
    <category field="social_science"/>
    <updated>2020-01-01T00:00:00+00:00</updated>
  </info>
  <citation>
    <layout prefix="(" suffix=")" delimiter="; ">
      <names variable="author"><name form="short"/></names>
      <date variable="issued" prefix=" "><date-part name="year"/></date>
    </layout>
  </citation>
  <bibliography>
    <layout><text variable="title" font-style="italic"/></layout>
  </bibliography>
</style>
"""

DEPENDENT = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" default-locale="de-DE">
  <info>
    <title>Zeitschrift für Beispiele</title>
    <id>http://www.zotero.org/styles/zeitschrift-fuer-beispiele</id>
    <link href="http://www.zotero.org/styles/zeitschrift-fuer-beispiele" rel="self"/>
    <link href="http://www.zotero.org/styles/muster-stil" rel="independent-parent"/>
    <category citation-format="author-date"/>
    <updated>2021-01-01T00:00:00+00:00</updated>
  </info>
</style>
"""

INDEX = [
    {"title": "American Psychological Association 7th edition", "titleShort": "APA", "name": "apa", "dependent": 0,
     "categories": {"format": "author-date", "fields": ["psychology"]}, "updated": "2024", "href": "https://www.zotero.org/styles/apa"},
    {"title": "Zürcher Hochschule für Angewandte Wissenschaften", "titleShort": "ZHAW", "name": "zhaw", "dependent": 0,
     "categories": {"format": "author-date", "fields": ["generic-base"]}, "updated": "2024", "href": ""},
    {"title": "Zeitschrift für Beispiele", "name": "zeitschrift-fuer-beispiele", "dependent": 1,
     "categories": {"format": "author-date", "fields": ["social_science"]}, "updated": "2021", "href": ""},
    {"title": "Nature", "name": "nature", "dependent": 0, "categories": {"format": "numeric", "fields": ["science"]},
     "updated": "2024", "href": ""},
]


class FakeRepo:
    """zotero.org: styles.json mit Last-Modified (304 bei unverändert), einzelne Stile."""

    def __init__(self):
        self.requests: list[tuple[str, str | None]] = []
        self.online = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.online:
            raise httpx.ConnectError("offline")
        self.requests.append((request.url.path, request.headers.get("If-Modified-Since")))
        if request.url.path == "/styles-files/styles.json":
            if request.headers.get("If-Modified-Since") == "Mon, 26 Oct 2026 16:10:09 GMT":
                return httpx.Response(304)
            return httpx.Response(200, json=INDEX, headers={"Last-Modified": "Mon, 26 Oct 2026 16:10:09 GMT"})
        name = request.url.path.rsplit("/", 1)[-1]
        styles = {"muster-stil": STYLE, "zeitschrift-fuer-beispiele": DEPENDENT}
        return httpx.Response(200, text=styles[name]) if name in styles else httpx.Response(404)

    def factory(self):
        return lambda: httpx.Client(transport=httpx.MockTransport(self.handle), base_url="https://www.zotero.org")


def test_index_loaded_only_when_searching_and_then_conditionally(tmp_path, monkeypatch):
    fake = FakeRepo()
    repo = csl.Repository(tmp_path / "cache", fake.factory())
    assert fake.requests == []  # nichts im Voraus
    res = repo.search("zurcher hochschule")
    assert [r["name"] for r in res["results"]] == ["zhaw"] and res["count"] == 4
    assert [r["name"] for r in repo.search("", fmt="numeric")["results"]] == ["nature"]
    assert len(fake.requests) == 1  # weitere Suchen aus dem Speicher
    # Später (nach 10 Minuten, neues Programm): nur noch bedingt nachfragen – unverändert, also 304 ohne Inhalt
    meta = json.loads((tmp_path / "cache" / "styles-index.meta.json").read_text())
    meta["checked_at"] -= 3600
    (tmp_path / "cache" / "styles-index.meta.json").write_text(json.dumps(meta))
    repo2 = csl.Repository(tmp_path / "cache", fake.factory())
    assert repo2.search("apa")["results"][0]["name"] == "apa"
    assert fake.requests[-1] == ("/styles-files/styles.json", "Mon, 26 Oct 2026 16:10:09 GMT")
    # Offline: die gespeicherte Liste reicht
    fake.online = False
    meta = json.loads((tmp_path / "cache" / "styles-index.meta.json").read_text())
    meta["checked_at"] -= 3600
    (tmp_path / "cache" / "styles-index.meta.json").write_text(json.dumps(meta))
    res = csl.Repository(tmp_path / "cache", fake.factory()).search("nature")
    assert res["offline"] and res["results"][0]["name"] == "nature"


def test_own_style_from_dependent_keeps_text_and_gets_own_id(tmp_path):
    fake = FakeRepo()
    fetched = csl.Repository(tmp_path / "cache", fake.factory()).fetch("zeitschrift-fuer-beispiele")
    assert fetched["info"]["dependent"] and "muster-stil" in fetched["parent_xml"]
    base, title, template = csl.editable_copy(fetched["xml"], fetched["parent_xml"], "Beispiele (angepasst)")
    store = csl.StyleStore(tmp_path / "styles")
    slug, xml = store.create(base, title, template)
    meta = csl.info(xml)
    assert slug == "beispiele-angepasst" and meta["id"] == csl.ID_PREFIX + slug and meta["own"]
    assert meta["title"] == "Beispiele (angepasst)" and meta["template"].endswith("/zeitschrift-fuer-beispiele")
    assert meta["default_locale"] == "de-DE" and not meta["dependent"]
    assert "<!-- Kommentar bleibt erhalten -->" in xml and "<title-short>" not in xml
    assert '<names variable="author"><name form="short"/></names>' in xml  # Rest unverändert
    assert xml.count('rel="self"') == 1
    # Zweiter Stil gleichen Titels: eigener Name
    assert store.create(base, title, template)[0] == "beispiele-angepasst-2"


def test_save_keeps_versions_and_enforces_own_id(tmp_path):
    store = csl.StyleStore(tmp_path / "styles")
    slug, xml = store.create(STYLE, "Mein Stil", "http://www.zotero.org/styles/muster-stil")
    changed = xml.replace('font-style="italic"', 'font-weight="bold"').replace(csl.ID_PREFIX + slug, "http://example.org/x")
    saved = store.save(slug, changed)
    assert 'font-weight="bold"' in saved and csl.info(saved)["id"] == csl.ID_PREFIX + slug
    assert len(store.versions(slug)) == 1
    old = store.version(slug, store.versions(slug)[0]["name"])
    assert 'font-style="italic"' in old
    assert store.save(slug, saved) == saved and len(store.versions(slug)) == 1  # unverändert: keine neue Version
    store.delete(slug)
    assert store.list() == []


def test_check_reports_problems():
    assert csl.check(STYLE) == []
    with pytest.raises(csl.CslError):
        csl.check("<style>kaputt")
    with pytest.raises(csl.CslError):
        csl.check("<html/>")
    assert csl.check(STYLE.replace("<citation>", "<x>").replace("</citation>", "</x>"))


@pytest.fixture
def client(zengine, fake_zotero, monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(csl, "_client", fake.factory())
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    with TestClient(create_app(zengine)) as c:
        c.fake_repo = fake
        yield c


def test_api_create_edit_install(client, fake_zotero):
    assert client.get("/api/csl/repository", params={"q": "apa"}).json()["results"][0]["name"] == "apa"
    src = client.get("/api/csl/repository/muster-stil").json()
    r = client.post("/api/csl/styles", json={"xml": src["xml"], "title": "Muster (angepasst)"}, headers=H).json()
    slug = r["slug"]
    assert r["info"]["own"] and client.get("/api/csl/styles").json()["styles"][0]["slug"] == slug
    edited = r["xml"].replace('prefix="("', 'prefix="["')
    r = client.put(f"/api/csl/styles/{slug}", json={"xml": edited}, headers=H).json()
    assert 'prefix="["' in r["xml"] and len(r["versions"]) == 1
    bad = client.put(f"/api/csl/styles/{slug}", json={"xml": "<style"}, headers=H)
    assert bad.status_code == 400
    # In Zotero installieren (Plugin ab 1.0.0)
    assert client.post(f"/api/csl/styles/{slug}/install", headers=H).json()["installed"]
    assert list(fake_zotero.installed_styles) == [csl.ID_PREFIX + slug]
    fake_zotero.plugin_version = (0, 9)
    r = client.post(f"/api/csl/styles/{slug}/install", headers=H)
    assert r.status_code == 409 and "Plugin" in r.json()["detail"]
    assert client.delete(f"/api/csl/styles/{slug}", headers=H).json()["deleted"] == slug
    assert client.get(f"/api/csl/styles/{slug}").status_code == 404


def test_api_items_for_preview(client, fake_zotero):
    fake_zotero.add_item("ITEMC001", "Ein Buch über Beispiele", "Muster", "2022")
    items =client.post("/api/csl/items", json={"items": ["users/0:ITEMC001"]}, headers=H).json()["items"]
    assert items and items[0]["id"] == "users/0:ITEMC001" and items[0]["title"] == "Ein Buch über Beispiele"


def test_item_types_from_zotero_schema(client, fake_zotero, monkeypatch):
    """Weitere Eintragsarten: Liste und Namen aus Zotero, Beispiele wie in Zotero nach CSL-JSON umgesetzt."""
    from zotivity import csl_types

    monkeypatch.setattr(csl_types, "_memory", {"schema": None, "at": 0.0})
    r = client.get("/api/csl/item-types", params={"lang": "de"}).json()
    assert r["source"] == "zotero"
    by_type = {x["type"]: x for x in r["types"]}
    # Standardbeispiele (Buch) und Notizen fehlen; sortiert nach Namen
    assert [x["label"] for x in r["types"]] == ["Gerichtsentscheidung", "Hologramm", "Kunstwerk"]
    case = by_type["case"]["item"]
    assert case["type"] == "legal_case" and case["title"] == "Brown v. Board of Education" and case["authority"] == "U.S. Supreme Court"
    assert case["container-title"] == "U.S." and case["volume"] == "347" and case["page"] == "483"
    assert case["issued"] == {"date-parts": [[1954, 5, 17]]} and case["__locator"] == "495" and case["id"] == "z:case"
    # Die Hauptrolle der Art wird zu „author“ (wie in Zotero)
    art = by_type["artwork"]["item"]
    assert art["type"] == "graphic" and art["author"] == [{"family": "Mendel", "given": "Clara"}] and art["medium"] == "Oil on canvas"
    # Neue Art ohne eigenes Beispiel: allgemeines aus ihren Feldern
    holo = by_type["hologram"]["item"]
    assert holo["title"] == "Example title" and holo["publisher"] == "Example Publisher" and holo["author"][0]["family"] == "Doe"
    assert holo["type"] == "document"
    assert client.get("/api/csl/item-types", params={"lang": "en"}).json()["types"][0]["label"] == "Artwork"
    # Ohne Zotero: zuletzt gespeichertes Schema
    monkeypatch.setattr(csl_types, "_memory", {"schema": None, "at": 0.0})
    monkeypatch.setattr(fake_zotero, "schema", {"broken": True})
    r = client.get("/api/csl/item-types").json()
    assert r["source"] == "cache" and len(r["types"]) == 3



def test_library_examples_pick_matching_items(client, zengine):
    """Beispiele aus der eigenen Bibliothek: passende Eintragsart und Personen, sonst kein Treffer (→ erfundenes)."""
    def item(key, itype, authors=0, editors=0, year="2020", **extra):
        creators = [{"creatorType": "author", "lastName": f"A{i}", "firstName": "X"} for i in range(authors)]
        creators += [{"creatorType": "editor", "lastName": f"E{i}", "firstName": "Y"} for i in range(editors)]
        return {"key": key, "version": 1, "data": {"key": key, "itemType": itype, "title": f"Titel {key}", "creators": creators,
                                                    "date": year, **extra}, "meta": {"parsedDate": year}}

    zengine.store.upsert_items("users/0", [
        item("ART4AAAA", "journalArticle", authors=4, publicationTitle="Zeitschrift", DOI="10.1/x"),
        item("ART2AAAA", "journalArticle", authors=2, publicationTitle="Zeitschrift"),
        item("ART2BBBB", "journalArticle", authors=2),  # weniger vollständig
        item("EDITAAAA", "book", editors=2),
        item("CASEAAAA", "case"),
    ])
    r = client.post("/api/csl/library-examples", json={"examples": ["article4", "article", "edited", "book", "z:case", "z:film"]},
                    headers=H).json()["items"]
    assert {ex: x["ref"] for ex, x in r.items()} == {"article4": "users/0:ART4AAAA", "article": "users/0:ART2AAAA",
                                                    "edited": "users/0:EDITAAAA", "z:case": "users/0:CASEAAAA"}
    assert r["article4"]["item"]["id"] == "lib:article4" and r["article4"]["title"] == "Titel ART4AAAA"


def test_collection_examples(client, zengine, monkeypatch):
    """Eine Sammlung als Beispiele: ihre Einträge samt Untersammlungen, nach Eintragsart sortiert, mit Namen aus Zotero."""
    from zotivity import csl_types

    monkeypatch.setattr(csl_types, "_memory", {"schema": None, "at": 0.0})
    store = zengine.store
    store.replace_collections("users/0", [{"key": "COLAAAAA", "data": {"name": "Testfälle", "parentCollection": False}},
                                          {"key": "COLBBBBB", "data": {"name": "Bücher", "parentCollection": "COLAAAAA"}}])

    def item(key, itype, cols):
        return {"key": key, "version": 1, "meta": {"parsedDate": "2020"},
                "data": {"key": key, "itemType": itype, "title": f"Titel {key}", "date": "2020", "collections": cols,
                         "creators": [{"creatorType": "author", "lastName": "Muster", "firstName": "A."}]}}

    store.upsert_items("users/0", [item("ITEMXXXX", "journalArticle", ["COLAAAAA"]), item("ITEMYYYY", "book", ["COLBBBBB"]),
                                   item("ITEMZZZZ", "book", [])])
    r = client.post("/api/csl/collection-examples", json={"collection": "users/0:COLAAAAA", "lang": "de"}, headers=H).json()
    assert r["total"] == 2 and [x["ref"] for x in r["items"]] == ["users/0:ITEMYYYY", "users/0:ITEMXXXX"]
    assert r["items"][0]["label"] == "Buch" and r["items"][0]["item"]["id"] == "c:users/0:ITEMYYYY"
    assert client.post("/api/csl/collection-examples", json={"collection": "users/0:*"}, headers=H).status_code == 400
