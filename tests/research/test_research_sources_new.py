"""Neue Quellen ohne Netz: Antworten im Format, das die APIs am 29.10.2026 geliefert haben."""

from __future__ import annotations

import httpx
import pytest

from zotivity.research.errors import SourceError
from zotivity.research.querybuild import build_all, translate
from zotivity.research.sources import catalog
from zotivity.research.sources.arxiv import ArXiv
from zotivity.research.sources.econbiz import EconBiz
from zotivity.research.sources.eric import ERIC
from zotivity.research.sources.europepmc import EuropePMC
from zotivity.research.sources.osf import OSFPreprints
from zotivity.research.sources.semanticscholar import SemanticScholar
from zotivity.research.sources.swisscovery import Swisscovery


def epmc_handler(req):
    cursor = req.url.params.get("cursorMark")
    if req.url.params.get("resultType") == "idlist":
        return httpx.Response(200, json={"hitCount": 53})
    r = {"id": "40779411", "source": "MED", "pmid": "40779411", "doi": "10.1177/21522715251360547",
         "title": "The Different Structure and Predictors of Online Aggression.", "pubYear": "2025",
         "abstractText": "Online aggression <i>is</i> common among adolescents and young adults today.",
         "language": "eng", "authorList": {"author": [{"lastName": "Zhu", "firstName": "Wenfeng"}]},
         "journalInfo": {"volume": "28", "issue": "4", "journal": {"title": "Cyberpsychology, behavior and social networking",
                                                                    "issn": "2152-2715"}},
         "pageInfo": "1-9", "meshHeadingList": {"meshHeading": [{"descriptorName": "Adolescent"}]},
         "firstPublicationDate": "2025-08-01", "citedByCount": 3}
    if cursor == "*":
        return httpx.Response(200, json={"hitCount": 2, "nextCursorMark": "C2", "resultList": {"result": [r]}})
    return httpx.Response(200, json={"hitCount": 2, "nextCursorMark": "C2",
                                     "resultList": {"result": [{**r, "id": "PPR1", "source": "PPR", "pmid": None,
                                                                "doi": "10.1101/x", "journalInfo": None}]}})


def test_europepmc(sim):
    sim.extra["www.ebi.ac.uk"] = epmc_handler
    src = EuropePMC(sim.http(), email="a@b.c")
    assert src.count('TITLE:"online aggression"', {"year_from": 2020}).count == 53
    assert sim.calls[-1][2]["query"] == '(TITLE:"online aggression") AND PUB_YEAR:[2020 TO 3000]'
    res = src.search("x")
    assert res.count == 2 and len(res.records) == 2
    a, b = res.records
    assert a["title"] == "The Different Structure and Predictors of Online Aggression" and a["abstract"].startswith("Online aggression is")
    assert (a["pmid"], a["lang"], a["container"], a["volume"], a["year"]) == ("40779411", "en", "Cyberpsychology, behavior and social networking", "28", 2025)
    assert b["type"] == "preprint" and b["container"] == "Preprint"


def test_eric(sim):
    sim.extra["api.ies.ed.gov"] = lambda req: httpx.Response(200, json={"response": {"numFound": 1, "docs": [
        {"id": "EJ1395349", "title": "Navigating Privacy Tensions When Responding to Online Aggression",
         "author": ["Byrne, Virginia L.", "Kumar, Priya C."], "description": "Postsecondary institutions have a duty.",
         "publicationtype": ["Journal Articles", "Reports - Descriptive"], "publicationdateyear": 2023,
         "language": ["English"], "issn": ["ISSN-0007-1013"], "subject": ["Aggression", "Privacy"], "peerreviewed": "T",
         "publisher": "Wiley. Available from: John Wiley & Sons"}]}})
    src = ERIC(sim.http())
    assert src.count("x", {"year_from": 2006, "year_to": 2026}).count == 1
    assert sim.calls[-1][2]["search"] == "(x) AND publicationdateyear:[2006 TO 2026]" and sim.calls[-1][2]["rows"] == "0"
    rec = src.search("x").records[0]
    assert rec["authors"][0] == ["Byrne", "Virginia L."] and rec["accession"] == "EJ1395349" and rec["issn"] == "0007-1013"
    assert rec["publisher"] == "Wiley" and rec["lang"] == "en" and rec["url"].endswith("EJ1395349")


def test_econbiz_paging(sim):
    def handler(req):
        start, size = int(req.url.params["from"]), int(req.url.params["size"])
        hits = [{"id": str(i), "title": f"Cyberbullying, ostracism : study {i}", "creator": ["Shao, Zhen"],
                 "contributor": ["Meyer, Natanya"], "date": ["2025"], "type": "article",
                 "identifier_url": ["https://example.org/x", f"https://doi.org/10.4102/sajbm.{i}"],
                 "isPartOf": ["South African journal of business management ; 56.2025, 1, 1-12"], "subject": ["Mobbing"]}
                for i in range(start, min(start + size, 151))]
        return httpx.Response(200, json={"hits": {"total": 150, "hits": hits}})
    sim.extra["api.econbiz.de"] = handler
    res = EconBiz(sim.http()).search("cyberbullying", max_records=150)
    assert len(res.records) == 150 and any("Abstracts" in w for w in res.warnings)
    first = res.records[0]
    assert first["doi"] == "10.4102/sajbm.1" and first["container"] == "South African journal of business management"
    assert first["title"] == "Cyberbullying, ostracism: study 1" and first["authors"] == [["Shao", "Zhen"], ["Meyer", "Natanya"]]
    assert [c[2]["from"] for c in sim.calls if c[0] == "api.econbiz.de"] == ["1", "101"]


def test_semanticscholar(sim):
    def handler(req):
        if req.url.path.endswith("/bulk"):
            assert req.headers.get("x-api-key") == "S2KEY" and req.url.params["year"] == "2010-"
            return httpx.Response(200, json={"total": 1, "token": None, "data": [{
                "paperId": "abc", "title": "Online aggression", "abstract": "Long abstract " * 5, "year": 2021,
                "externalIds": {"DOI": "10.1/s2", "PubMed": 123}, "journal": {"name": "J Youth", "volume": " 5", "pages": "1-2"},
                "authors": [{"name": "Jane Doe"}], "publicationTypes": ["JournalArticle"], "citationCount": 7}]})
        return httpx.Response(404)
    sim.extra["api.semanticscholar.org"] = handler
    res = SemanticScholar(sim.http(), "S2KEY").search('"online aggression" + teen*', {"year_from": 2010})
    rec = res.records[0]
    assert (rec["doi"], rec["pmid"], rec["container"], rec["volume"], rec["authors"]) == ("10.1/s2", "123", "J Youth", "5", [["Doe", "Jane"]])


def test_semanticscholar_without_key_is_explained(sim):
    sim.extra["api.semanticscholar.org"] = lambda req: httpx.Response(429, json={"message": "Too Many Requests"})
    with pytest.raises(SourceError, match="Schlüssel"):
        SemanticScholar(sim.http()).count("x")


ATOM = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults>148</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2512.14700v2</id>
    <title>Context-Aware Detection of Online
      Harassment</title>
    <summary>Online harassment is a widespread concern.</summary>
    <published>2025-11-28T00:18:47Z</published>
    <arxiv:doi>10.48550/arXiv.2512.14700</arxiv:doi>
    <category term="cs.SI"/>
    <author><name>Pinxian Lu</name></author>
    <author><name>Munmun De Choudhury</name></author>
  </entry>
</feed>"""


def test_arxiv_respects_rate_limit(sim):
    sim.extra["export.arxiv.org"] = lambda req: httpx.Response(200, content=ATOM.encode())
    waits = []
    src = ArXiv(sim.http(), sleep=waits.append)
    assert src.count("(ti:x OR abs:x)", {"year_from": 2020}).count == 148
    assert sim.calls[-1][2]["max_results"] == "1" and "submittedDate:[202001010000 TO 210012312359]" in sim.calls[-1][2]["search_query"]
    rec = src.search("x", max_records=1).records[0]
    assert waits and waits[0] > 2.5  # zweite Anfrage frühestens 3 Sekunden nach der ersten
    assert rec["title"] == "Context-Aware Detection of Online Harassment" and rec["accession"] == "arXiv:2512.14700"
    assert rec["authors"][1] == ["De Choudhury", "Munmun"] and rec["type"] == "preprint" and rec["year"] == 2025


def test_osf(sim):
    item = {"@id": "https://osf.io/pc3hk", "title": [{"@value": "Adverse childhood experiences"}],
            "description": [{"@value": "Research has consistently found poorer outcomes."}],
            "identifier": [{"@value": "https://doi.org/10.31234/osf.io/pc3hk"}, {"@value": "https://osf.io/pc3hk"}],
            "publisher": [{"@id": "https://osf.io/preprints/psyarxiv", "name": [{"@value": "PsyArXiv"}]}],
            "dateCreated": [{"@value": "2023-05-22"}], "creator": [{"name": [{"@value": "Nerea Llerena"}]}],
            "keyword": [{"@value": "adolescence"}]}
    sim.extra["share.osf.io"] = lambda req: httpx.Response(200, json={"meta": {"total": 1}, "data": [item], "links": {}})
    src = OSFPreprints(sim.http())
    c = src.count("online aggression OR teasing", {"providers": ["psyarxiv", "socarxiv"]})
    assert c.count == 1 and c.warnings  # ODER geht in OSF nicht
    assert sim.calls[-1][2]["cardSearchFilter[publisher][any-of]"].endswith("/socarxiv")
    rec = src.search("online aggression").records[0]
    assert (rec["doi"], rec["container"], rec["year"], rec["type"]) == ("10.31234/osf.io/pc3hk", "PsyArXiv", 2023, "preprint")


SRU = """<?xml version="1.0" encoding="UTF-8"?><searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
<numberOfRecords>47</numberOfRecords><records><record><recordSchema>dc</recordSchema><recordData>
<srw_dc:dc xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:srw_dc="info:srw/schema/1/dc-schema">
<dc:title>Cybermobbing bei Jugendlichen : Grundlagen /</dc:title><dc:creator>Muster, Anna, author.</dc:creator>
<dc:type>text</dc:type><dc:date>2019</dc:date><dc:language>ger</dc:language><dc:publisher>Beltz</dc:publisher>
<dc:identifier>ISBN 978-3-407-25801-2</dc:identifier><dc:subject>Cybermobbing.</dc:subject>
</srw_dc:dc></recordData><recordIdentifier>991170635128405501</recordIdentifier></record></records></searchRetrieveResponse>"""


def test_swisscovery(sim):
    sim.extra["swisscovery.slsp.ch"] = lambda req: httpx.Response(200, content=SRU.encode())
    src = Swisscovery(sim.http())
    assert src.count('alma.all_for_ui="cybermobbing"').count == 47
    res = src.search('alma.all_for_ui="cybermobbing"', {"year_from": 2020}, max_records=1)
    assert res.records == []  # 2019 fällt weg (die Attrappe kennt die Jahresgrenze im Katalog nicht)
    assert sim.calls[-1][2]["query"] == 'alma.main_pub_date>=2020 and (alma.all_for_ui="cybermobbing")'
    rec = Swisscovery(sim.http()).search("x", max_records=1).records[0]
    assert rec["title"] == "Cybermobbing bei Jugendlichen : Grundlagen" and rec["authors"] == [["Muster", "Anna"]]
    assert (rec["isbn"], rec["lang"], rec["type"], rec["year"]) == ("978-3-407-25801-2", "de", "book", 2019)


def test_translate_targets():
    q = '(teasing[tiab] OR "cyber-teasing"[tiab]) AND adolescen*[tiab] NOT (cyberbully*[ti] OR mobbing[ti])'
    assert translate(q, "europepmc")["string"] == ('((TITLE:teasing OR ABSTRACT:teasing) OR (TITLE:"cyber-teasing" OR '
                                                  'ABSTRACT:"cyber-teasing")) AND (TITLE:adolescen* OR ABSTRACT:adolescen*) '
                                                  'NOT (TITLE:cyberbully* OR TITLE:mobbing)')
    assert translate(q, "semanticscholar")["string"] == '(teasing | "cyber-teasing") + adolescen* + -cyberbully* + -mobbing'
    assert translate(q, "arxiv")["string"].endswith("ANDNOT (ti:cyberbully OR ti:mobbing)")
    assert translate(q, "swisscovery")["string"].startswith('(alma.all_for_ui="teasing" or alma.all_for_ui="cyber-teasing") and')
    assert translate(q, "econbiz")["string"] == ('(teasing OR "cyber-teasing") AND adolescen* NOT (title:cyberbully* OR '
                                                'title:mobbing)')
    osf = translate(q, "osf")
    assert osf["string"] == "teasing adolescen" and osf["notes"]
    assert translate('"Adolescent"[Mesh] AND bullying', "europepmc")["string"] == 'MESH:"Adolescent" AND (TITLE:bullying OR ABSTRACT:bullying)'


def test_build_all_for_chosen_sources():
    blocks = [{"name": "A", "terms": ["teasing"]}, {"name": "B", "terms": ["youth"]}]
    out = build_all(blocks, ["eric", "osf", "unknown"])
    assert list(out) == ["pubmed", "openalex", "psycinfo", "wos", "eric", "osf"]
    assert out["eric"]["string"] == "(title:teasing OR description:teasing) AND (title:youth OR description:youth)"
    assert out["osf"]["string"] == "teasing youth"


def test_catalog_suggestions():
    s = catalog.suggest(["social", "psych"])
    assert "openalex" in s and "pubmed" in s and "osf" in s and "psycinfo" in s and "socindex" in s
    assert "scholar" not in s and "jstor" not in s and "arxiv" not in s
    assert catalog.suggest(["econ"]) == ["openalex", "econbiz"]
    art = catalog.suggest(["art"])  # eingebaute Quellen und Export-Datenbanken, nicht die noch nicht eingebauten
    assert {"openalex", "swisscovery", "iba", "artfulltext", "researchcatalogue", "kubikat"} <= set(art)
    assert not {"jstor", "doaj", "europeana", "artdok"} & set(art)
    assert all(set(x["disciplines"]) <= set(catalog.DISCIPLINES) for x in catalog.CATALOG)


def test_swisscovery_blocks_wildcards_years(sim):
    """Der Katalog wertet mehrere Klammerblöcke falsch aus: abgefragt wird der engste Block, der Rest nachträglich."""
    from zotivity.research.sources import swisscovery as sc

    sc._PLANS.clear()

    def record(title, subject):
        return (f"<record><recordData><srw_dc:dc xmlns:dc='http://purl.org/dc/elements/1.1/' xmlns:srw_dc='info:srw/schema/1/dc-schema'>"
                f"<dc:title>{title}</dc:title><dc:date>2021</dc:date><dc:subject>{subject}</dc:subject></srw_dc:dc></recordData>"
                f"<recordIdentifier>{abs(hash(title))}</recordIdentifier></record>")

    def handler(req):
        q = req.url.params["query"]
        n = 40 if "teasing" in q else 900  # Block „teasing“ ist der engste
        recs = "".join([record("Teasing among adolescents", "Jugendliche"), record("Teasing in kindergarten", "Kinder"),
                        record("Teasing and cyberbullying in adolescence", "Mobbing")]) if req.url.params["maximumRecords"] != "0" else ""
        return httpx.Response(200, content=(f'<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><numberOfRecords>{n}'
                                            f"</numberOfRecords><records>{recs}</records></searchRetrieveResponse>").encode())

    sim.extra["swisscovery.slsp.ch"] = handler
    q = translate('(teasing[tiab] OR "cyber-teasing"[tiab]) AND adolescen*[tiab] NOT cyberbully*[ti]', "swisscovery")["string"]
    assert 'alma.all_for_ui all "adolescen*"' in q  # Platzhalter nur mit „all“
    src = Swisscovery(sim.http())
    c = src.count(q)
    assert c.count == 80 and "Begriff für Begriff" in c.warnings[0] and c.upper_bound  # 2 Begriffe × 40
    asked = [call[2]["query"] for call in sim.calls if call[0] == "swisscovery.slsp.ch"]
    assert 'alma.all_for_ui="teasing" or alma.all_for_ui="cyber-teasing"' in asked  # Blöcke gezählt
    assert 'alma.all_for_ui="cyber-teasing" and (alma.all_for_ui all "adolescen*")' in asked  # nur ein Klammerblock
    res = src.search(q, max_records=10)
    titles = [r["title"] for r in res.records]  # adolescen* prüft der Katalog, cyberbully* im Titel die App
    assert titles == ["Teasing among adolescents", "Teasing in kindergarten"]
    assert any("Von 3 abgerufenen passen 2" in w for w in res.warnings)  # Doppelte aus beiden Teilabfragen nur einmal
    assert sc.term_cql(("term", "alma.title", "universit*", "=")) == 'alma.title all "universit*"'
    assert sc.term_clauses(("term", "alma.all_for_ui", "assistive technolog*", "=")) == [
        'alma.all_for_ui="assistive technology"', 'alma.all_for_ui="assistive technologies"']  # Phrase bleibt Phrase
    assert sc.matches(("term", "alma.all_for_ui", "technolog* assistive", "all"), {"title": "Assistive technologies at school"})
    assert sc.matches(("term", "alma.all_for_ui", "assistive technolog*", "="), {"title": "Assistive technologies at school"})
    assert not sc.matches(("term", "alma.all_for_ui", "screen reader", "="), {"title": "reader for the screen"})
    sc._PLANS.clear()
    src.count(q, {"year_from": 2020, "year_to": 2024})
    assert any(c[2]["query"].startswith("alma.main_pub_date>=2020 and alma.main_pub_date<=2024 and ") for c in sim.calls)
    tree = sc.parse_cql('(a="x" or a="y") and a="z" not (a="w")')
    assert tree[0] == "not" and tree[1][0] == "and"
