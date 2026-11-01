"""Übergabe an Zotero über die Attrappe des Ports: Plan, Bestätigung, Sammlungen, Crossref, Duplikatschutz."""

from __future__ import annotations

import pytest
from test_research_pool_screening import make_project

from zotivity.research.errors import ZoteroWriteRefused
from zotivity.research.export import collection_paths


def setup_pool(service, zotero):
    pid = make_project(service)["id"]
    q = service.add_query(pid, "T2", "openalex", "teasing")
    service.run_query(q["id"])
    return pid, {r["openalex_id"]: r["id"] for r in service.store.records(pid)}


def test_collection_paths():
    cols = [{"key": "A", "name": "Rollen", "parent": None}, {"key": "B", "name": "neu", "parent": "A"},
            {"key": "C", "name": "Teasing", "parent": None}]
    assert collection_paths(cols) == {"Rollen": "A", "Rollen/neu": "B", "Teasing": "C"}


def test_plan_and_export(service, zotero):
    zotero.cols = {"A": {"key": "A", "name": "Rollen", "parent": None}, "B": {"key": "B", "name": "neu", "parent": "A"}}
    pid, ids = setup_pool(service, zotero)
    service.decide(pid, ids["W1"], "include", 1)  # Teasing/neu – Sammlung fehlt
    service.decide(pid, ids["W2"], "include", 2)  # Rollen/neu – vorhanden

    plan = service.export_plan(pid)
    assert plan["can_write"] and plan["create_collections"] == ["Teasing/neu"]
    by_slot = {f["slot"]: f for f in plan["folders"]}
    assert len(by_slot[1]["new"]) == 1 and by_slot[2]["collection_key"] == "B"
    assert zotero.writes == []  # der Plan liest nur

    with pytest.raises(ZoteroWriteRefused):
        service.export(pid, confirm=False)
    assert zotero.writes == []

    res = service.export(pid, confirm=True)
    assert res["created"] == 2 and res["linked"] == 0 and not res["failed"]
    assert res["collections_created"] == ["Teasing", "Teasing/neu"]
    assert res["enriched"] == 1  # 10.1/xyz kennt Crossref
    items = [it["data"] for it in zotero.items.values()]
    stress = next(d for d in items if d["title"].startswith("Digital stress"))
    assert stress["collections"] == ["B"] and {"tag": "litsearch"} in stress["tags"]
    assert stress["creators"][0] == {"creatorType": "author", "lastName": "Doe", "firstName": "Jane M."}
    assert stress["libraryCatalog"] == "OpenAlex" and "OpenAlex: W2" in stress["extra"]

    again = service.export_plan(pid)
    assert again["totals"] == {"new": 0, "link": 0, "done": 2}
    n_writes = len(zotero.writes)
    service.export(pid, confirm=True)
    assert len(zotero.writes) == n_writes  # nichts doppelt


def test_existing_items_are_linked_not_duplicated(service, zotero):
    zotero.cols = {"T": {"key": "T", "name": "Teasing", "parent": None}, "N": {"key": "N", "name": "neu", "parent": "T"}}
    zotero.items = {"OLD": {"key": "OLD", "version": 3, "data": {"title": "Teasing online among adolescents", "DOI": "10.1/abc", "collections": []}}}
    pid, ids = setup_pool(service, zotero)
    service.zotero_match(pid)
    service.decide(pid, ids["W1"], "include", 1)
    plan = service.export_plan(pid)
    assert plan["totals"] == {"new": 0, "link": 1, "done": 0}
    res = service.export(pid, confirm=True)
    assert res == {**res, "created": 0, "linked": 1}
    assert zotero.items["OLD"]["data"]["collections"] == ["N"]
    assert ("items", "users/0", 0) not in zotero.writes and not any(w[0] == "items" for w in zotero.writes)


def test_no_write_access(service, zotero):
    zotero.writable = False
    pid, ids = setup_pool(service, zotero)
    service.decide(pid, ids["W1"], "include", 1)
    with pytest.raises(ZoteroWriteRefused):
        service.export(pid, confirm=True)
    assert zotero.writes == []


def test_unassigned_folder(service, zotero):
    pid, ids = setup_pool(service, zotero)
    service.decide(pid, ids["W1"], "include", 5)  # Ordner 5 ist nicht zugeordnet
    plan = service.export_plan(pid)
    assert len(plan["unassigned"]) == 1 and plan["totals"]["new"] == 0
