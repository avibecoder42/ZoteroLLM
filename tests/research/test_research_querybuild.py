"""Konzeptblöcke → Suchstrings je Quelle; PubMed → OpenAlex."""

from __future__ import annotations

import pytest
from research_fakes import QUERIES

from zotivity.research.querybuild import build, build_all, pubmed_to_openalex

BLOCKS = [
    {"name": "Population", "terms": ["adolescen*", "teen*", '"young people"'], "mesh": ["Adolescent"], "psycinfo": []},
    {"name": "Phänomen", "terms": ["cyber-aggression", "online harassment"], "psycinfo": ["Cyberbullying"]},
    {"name": "leer", "terms": []},
    {"name": "Ausschluss", "kind": "exclude", "field": "ti", "terms": ["cyberbully*"]},
]


def test_pubmed():
    s = build("pubmed", BLOCKS)["string"]
    assert s == ('(adolescen*[tiab] OR teen*[tiab] OR "young people"[tiab] OR "Adolescent"[Mesh]) AND '
                 '("cyber-aggression"[tiab] OR "online harassment"[tiab]) NOT cyberbully*[ti]')


def test_openalex_drops_wildcards_and_mesh():
    r = build("openalex", BLOCKS)
    assert r["string"] == ('(adolescen OR teen OR "young people") AND ("cyber-aggression" OR "online harassment") '
                           'NOT cyberbully')
    assert any("Platzhalter" in n for n in r["notes"]) and any("MeSH" in n for n in r["notes"])


def test_ovid_lines():
    r = build("psycinfo", BLOCKS)
    assert r["lines"] == [
        '(adolescen* or teen* or "young people").ti,ab,id.',
        '(cyber-aggression or "online harassment").ti,ab,id. or exp Cyberbullying/',
        "cyberbully*.ti.",
        "1 and 2 not 3",
    ]


def test_wos():
    assert build("wos", BLOCKS)["string"] == ('TS=(adolescen* OR teen* OR "young people") AND '
                                              'TS=(cyber-aggression OR "online harassment") NOT TI=(cyberbully*)')


def test_empty_and_unknown():
    assert all(not v["string"] for v in build_all([]).values())
    with pytest.raises(ValueError):
        build("scopus", BLOCKS)


def test_pubmed_to_openalex():
    r = pubmed_to_openalex('(coping[tiab] OR "de-escalat*"[tiab] OR help-seeking[tiab]) AND "Internet"[Mesh] '
                           'NOT (cyberbully*[ti] OR cyber-bully*[ti])')
    assert r["string"] == ('(coping OR "de-escalat" OR "help-seeking") AND "Internet" NOT (cyberbully OR "cyber-bully")')
    assert len(r["notes"]) == 3  # MeSH, Titel, Platzhalter


@pytest.mark.skipif(not QUERIES.exists(), reason="Suchstrings des Projekts nicht vorhanden")
def test_translates_project_files():
    for f in QUERIES.glob("*.txt"):
        r = pubmed_to_openalex(f.read_text(encoding="utf-8-sig"))
        s = r["string"]
        assert "[" not in s and "*" not in s and "," not in s, f.name
        assert s.count("(") == s.count(")") and s.count('"') % 2 == 0, f.name
