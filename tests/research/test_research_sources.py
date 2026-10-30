"""Quellen ohne Netz: PubMed, OpenAlex, Crossref, RIS und die Wiederholung bei 429."""

from __future__ import annotations

from zotllm.research.sources import ris
from zotllm.research.sources.crossref import Crossref, enrich
from zotllm.research.sources.openalex import OpenAlex, abstract_from_index, work_to_rec
from zotllm.research.sources.pubmed import PubMed


def test_pubmed_count_and_search(sim):
    pm = PubMed(sim.http(), api_key="KEY", sleep=lambda s: None)
    c = pm.count('"online aggression"[tiab] OR "peace and quiet"[tiab]', {"year_from": 2006})
    assert c.count == 2
    assert c.translation.startswith("translated(")
    assert any("peace and quiet" in w for w in c.warnings)
    esearch = [x for x in sim.calls if x[1].endswith("esearch.fcgi")]
    assert esearch  # NCBI-Schlüssel und Limits gehen als Formular mit

    res = pm.search("x")
    assert res.count == 2 and len(res.records) == 2
    r = res.records[0]
    assert r["pmid"] == "111" and r["doi"] == "10.1/abc"
    assert r["title"] == "Teasing online among adolescents"  # Schlusspunkt entfernt
    assert r["authors"][0] == ["Doe", "Jane"]
    assert r["abstract"].startswith("BACKGROUND: ")
    assert r["lang"] == "en" and "Adolescent" in r["subjects"]
    assert r["container"] == "J Youth" and r["volume"] == "12"


def test_pubmed_batches_and_limit(sim):
    sim.pubmed_articles = [sim.pubmed_articles[0]] * 450
    res = PubMed(sim.http(), sleep=lambda s: None).search("x", max_records=450)
    assert len(res.records) == 450
    assert sum(1 for x in sim.calls if x[1].endswith("efetch.fcgi")) == 3  # 200 + 200 + 50


def test_openalex_count_search_and_mapping(sim):
    oa = OpenAlex(sim.http(), mailto="a@b.c")
    assert oa.count("teasing AND teen*").count == 2
    params = sim.calls[-1][2]
    assert params["filter"].startswith("title_and_abstract.search:teasing AND teen*")
    assert params["mailto"] == "a@b.c"

    res = oa.search('teasing, "online"', {"year_from": 2006, "types": ["article", "review"]}, max_records=1)
    assert len(res.records) == 1
    f = sim.calls[-1][2]["filter"]
    assert "publication_year:>2005" in f and "type:article|review" in f and "," not in f.split(",")[0][len("title_and_abstract.search:"):]
    assert any("Kommas" in w for w in res.warnings)
    rec = res.records[0]
    assert rec["openalex_id"] == "W1" and rec["pmid"] == "111" and rec["doi"] == "10.1/ABC"
    assert rec["abstract"] == "Online conflict among teens"
    assert rec["authors"] == [["Doe", "Jane"], ["van Beethoven", "Ludwig"]]
    assert rec["pages"] == "100-120" and rec["container"] == "New Media & Society"


def test_openalex_cursor_paging(sim):
    sim.openalex_works = [sim.openalex_works[1]] * 450
    res = OpenAlex(sim.http()).search("x", max_records=450)
    assert len(res.records) == 450
    assert sum(1 for x in sim.calls if x[0] == "api.openalex.org") == 3


def test_abstract_from_index():
    assert abstract_from_index({"b": [1], "a": [0, 2]}) == "a b a"
    assert abstract_from_index(None) == ""
    assert work_to_rec({"id": "https://openalex.org/W9"})["openalex_id"] == "W9"


def test_crossref_and_enrich(sim):
    cr = Crossref(sim.http(), mailto="a@b.c")
    assert cr.work("10.1/missing") is None
    msg = cr.work("https://doi.org/10.1/XYZ")
    assert msg["authors"][0] == ["Doe", "Jane M."] and msg["pages"] == "100-120" and msg["year"] == 2022
    oa = work_to_rec(sim.openalex_works[1])
    merged = enrich(oa, msg)
    assert merged["authors"][0] == ["Doe", "Jane M."]  # genaue Namen statt geteilter OpenAlex-Namen
    assert merged["abstract"] == oa["abstract"]  # vorhandene Felder bleiben


def test_http_retries_on_429(sim):
    sim.fail_once.add(("api.openalex.org", "/works"))
    assert OpenAlex(sim.http()).count("x").count == 2
    assert sum(1 for x in sim.calls if x[0] == "api.openalex.org") == 2


OVID = """TY  - JOUR
ID  - 2021-12345-001
AN  - 2021-12345-001
T1  - Cyberostracism and „social“ pain in adolescents
A1  - M\xfcller, Anna
A1  - Smith, J.
Y1  - 2021//
JF  - Journal of Adolescence
VL  - 88
IS  - 2
SP  - 10
EP  - 20
KW  - Ostracism; Social Media
KW  - Adolescent Development
LA  - English
N2  - Being excluded online hurts.
      The effect is larger for younger adolescents.
UR  - https://doi.org/10.1016/j.adolescence.2021.01.001
ER  -

TY  - CHAP
T1  - A chapter
A1  - Doe, Jane
A2  - Editor, Ed
T2  - The Book
SN  - 978-3-16-148410-0
PY  - 2019
ER  -
"""


def test_ris_ovid_cp1252():
    recs = ris.parse(OVID.encode("cp1252"))
    assert len(recs) == 2
    a, b = recs
    assert a["title"].startswith("Cyberostracism and „social“")
    assert a["authors"][0] == ["Müller", "Anna"]
    assert a["date"] == "2021" and a["pages"] == "10-20"
    assert a["doi"] == "10.1016/j.adolescence.2021.01.001"  # aus der URL
    assert a["abstract"] == "Being excluded online hurts. The effect is larger for younger adolescents."
    assert a["subjects"] == ["Ostracism", "Social Media", "Adolescent Development"]
    assert a["lang"] == "en" and a["accession"] == "2021-12345-001"
    assert b["type"] == "bookSection" and b["container"] == "The Book" and b["isbn"].startswith("978")
    assert b["editors"] == [["Editor", "Ed"]]
