"""Pool mit Duplikaterkennung, Vorfilter, Zotero-Abgleich, Screening mit Rückgängig, Protokoll."""

from __future__ import annotations

import pytest

from zotllm.research.errors import ResearchError
from zotllm.research.records import dedup_keys, normalize


def make_project(service, **kw):
    return service.create_project({"title": "Jugendliche und Onlineaggressionen", "criteria_out": "Cyberbullying\nkeine Jugendlichen",
                                   "folder_map": [{"slot": 1, "label": "Teasing", "path": "Teasing/neu"},
                                                  {"slot": 2, "label": "Rollen", "path": "Rollen/neu"}], **kw})


def test_dedup_across_sources(service, sim):
    p = make_project(service)
    pid = p["id"]
    qp = service.add_query(pid, "T2_Teasing", "pubmed", "teasing[tiab]")
    qo = service.add_query(pid, "T2_Teasing", "openalex", "teasing")
    r1 = service.run_query(qp["id"])
    assert (r1["fetched"], r1["new"], r1["duplicates"]) == (2, 2, 0)
    r2 = service.run_query(qo["id"])
    assert (r2["fetched"], r2["new"], r2["duplicates"]) == (2, 1, 1)  # W1 = PMID 111 (DOI in anderer Schreibweise)

    recs = {r["title"]: r for r in service.store.records(pid)}
    assert len(recs) == 3
    merged = recs["Teasing online among adolescents"]
    assert merged["pmid"] == "111" and merged["openalex_id"] == "W1"
    assert {f["source"] for f in merged["found"]} == {"pubmed", "openalex"}
    s = service.summary(pid)
    assert s["sources"] == {"pubmed": 2, "openalex": 2} and s["pool"] == 3


def test_title_match_respects_years_and_ids(service):
    pid = make_project(service)["id"]
    run = service.store.add_run(pid, kind="import", source="ris")
    title = "Digital drama among adolescents in group chats"
    stats = service.store.add_records(pid, run, [
        {"title": title, "year": 2015},
        {"title": title, "year": 2016, "abstract": "filled"},   # gleiche Arbeit, Abstract wird ergänzt
        {"title": title, "year": 2024},                         # andere Arbeit (Jahr weit weg)
        {"title": title + ".", "doi": "10.9/one", "year": 2015},  # gleiche Arbeit, DOI wird ergänzt
        {"title": "Editorial"},                                   # zu kurz für den Titelabgleich, aber eigener Datensatz
    ])
    assert stats["new"] == 3
    recs = service.store.records(pid)
    first = next(r for r in recs if r["year"] == 2015)
    assert first["abstract"] == "filled" and first["doi"] == "10.9/one"


def test_keys():
    k = dedup_keys(normalize({"doi": "https://doi.org/10.1/ABC.", "pmid": "1", "openalex_id": "https://openalex.org/w5",
                              "title": "A sufficiently long title"}))
    assert k == {"doi:10.1/abc", "pmid:1", "oa:W5", "title:asufficientlylongtitle"}


def test_prefilters_and_zotero_match(service, zotero):
    pid = make_project(service)["id"]
    run = service.store.add_run(pid, kind="import", source="ris")
    service.store.add_records(pid, run, [
        {"title": "Cyberbullying victimization in middle school", "abstract": "x" * 80, "lang": "en"},
        {"title": "Teasing and banter in WhatsApp groups", "abstract": "y" * 80, "lang": "en", "doi": "10.5/known"},
        {"title": "Ausgrenzung in Klassenchats von Jugendlichen", "abstract": "", "lang": "de"},
        {"title": "Conflits en ligne chez les adolescents", "abstract": "z" * 80, "lang": "fr"},
    ])
    zotero.items = {"K1": {"key": "K1", "version": 1, "data": {"title": "Something else", "DOI": "10.5/KNOWN"}}}
    m = service.zotero_match(pid)
    assert m == {"library": "users/0", "items": 1, "matches": 1}

    p = service.get_project(pid)
    pre = p["prefilters"]
    assert [f["kind"] for f in pre] == ["in_zotero", "no_abstract", "language"]
    pre.append({"kind": "title", "pattern": "bully* OR mobbing", "active": True})
    for f in pre:
        if f["kind"] == "no_abstract":
            f["active"] = True
    service.update_project(pid, {"prefilters": pre})
    pool = service.pool(pid)
    assert pool["total"] == 4 and pool["hidden"] == 3
    assert [it["title"] for it in pool["items"]] == ["Conflits en ligne chez les adolescents"]
    counts = {f["kind"]: f["count"] for f in pool["prefilters"]}
    assert counts == {"in_zotero": 1, "no_abstract": 1, "language": 1, "title": 1}  # „language“ ist aus: würde 1 ausblenden
    assert len(service.pool(pid, show_hidden=True)["items"]) == 4
    assert service.summary(pid)["visible"] == 1


def test_screening_decide_and_undo(service):
    pid = make_project(service)["id"]
    run = service.store.add_run(pid, kind="import", source="ris")
    service.store.add_records(pid, run, [{"title": f"Record number {i} about online conflict", "abstract": "a" * 60} for i in range(3)])
    q = service.queue(pid)
    ids = [it["id"] for it in q["items"]]
    assert len(ids) == 3 and q["criteria_out"] == ["Cyberbullying", "keine Jugendlichen"]

    service.decide(pid, ids[0], "include", 2)
    service.decide(pid, ids[1], "exclude", reason="Cyberbullying")
    service.decide(pid, ids[1], "maybe")
    with pytest.raises(ResearchError):
        service.decide(pid, ids[2], "include")  # ohne Ordner
    s = service.summary(pid)
    assert (s["screened"], s["included"], s["maybe"], s["excluded"]) == (2, 1, 1, 0)

    undone = service.undo(pid)
    assert undone["record_id"] == ids[1] and undone["status"] == "maybe"
    assert service.queue(pid, "exclude")["items"][0]["decision"]["reason"] == "Cyberbullying"  # vorheriger Entscheid gilt wieder
    assert [it["id"] for it in service.queue(pid, "open")["items"]] == [ids[2]]
    assert len(service.store.decision_history(pid)) == 2


def test_query_versions(service):
    pid = make_project(service)["id"]
    q1 = service.add_query(pid, "K1", "pubmed", "a[tiab]")
    q2 = service.update_query(q1["id"], {"string": "a[tiab] OR b[tiab]"})
    assert q2["version"] == 2 and q2["id"] != q1["id"]
    q3 = service.update_query(q2["id"], {"limits": {"year_from": 2006}})
    assert q3["id"] == q2["id"] and q3["limits"] == {"year_from": 2006}
    assert [q["version"] for q in service.store.queries(pid)] == [2]
    assert [q["version"] for q in service.store.query_versions(q2["id"])] == [2, 1]


def test_import_query_files(service):
    pid = make_project(service)["id"]
    files = [{"filename": "T1_Ostracism.txt", "content": "ostracism[tiab]\n AND teen*[tiab]"}]
    out = service.import_query_files(pid, files)
    assert out[0]["name"] == "T1_Ostracism" and out[0]["string"] == "ostracism[tiab] AND teen*[tiab]"
    again = service.import_query_files(pid, files)
    assert again[0]["id"] == out[0]["id"]  # unverändert → keine neue Version


def test_ris_import_and_protocol(service, sim):
    pid = make_project(service, question="Wie gehen Jugendliche mit Onlineaggressionen um?")["id"]
    q = service.add_query(pid, "T2_Teasing", "pubmed", "teasing[tiab]", {"year_from": 2006})
    service.count_query(q["id"])
    service.run_query(q["id"])
    from test_research_sources import OVID

    r = service.import_ris(pid, "psycinfo.ris", OVID.encode("cp1252"), "psycinfo", "T1_Ostracism", "exp Ostracism/", 120)
    assert r["new"] == 2 and r["hits"] == 120
    with pytest.raises(ResearchError):
        service.import_ris(pid, "leer.ris", b"nothing here", "psycinfo")
    rid = service.store.records(pid)[0]["id"]
    service.decide(pid, rid, "include", 1)
    other = service.store.records(pid)[1]["id"]
    service.decide(pid, other, "exclude", reason="Cyberbullying")

    md, name, mime = service.protocol(pid, "md")
    assert name.startswith("Suchprotokoll_Jugendliche") and mime == "text/markdown"
    assert "## Suchen" in md and "| PubMed | `T2_Teasing` (v1) | 2006–… |" in md
    assert "translated(teasing[tiab])" in md and "APA PsycInfo (Ovid)" in md
    assert "eingeschlossen: 1" in md and "| Cyberbullying | 1 |" in md
    assert "### Teasing (1)" in md

    csv_runs, _, _ = service.protocol(pid, "runs")
    assert csv_runs.startswith("﻿Datum;Quelle;Name") and "psycinfo.ris" in csv_runs
    csv_recs, _, _ = service.protocol(pid, "records")
    assert "eingeschlossen;Teasing" in csv_recs


def test_pool_follows_latest_search_and_reset(service, sim):
    """Der Pool zeigt je Suchstring nur die letzte Suche; gelöschte Suchstrings verschwinden, Entschiedenes bleibt."""
    import pytest

    from zotllm.research.errors import ResearchError

    pid = make_project(service)["id"]
    q = service.add_query(pid, "T2_Teasing", "pubmed", "teasing[tiab]")
    service.run_query(q["id"])
    first = service.pool(pid)["items"]
    assert len(first) == 2
    service.decide(pid, first[0]["id"], "include", 1)
    service.run_query(q["id"], max_records=1)  # enger: nur noch 1 geholt
    items = service.pool(pid)["items"]
    latest = {it["id"] for it in items if not it["stale"]}
    assert len(latest) == 1 and {it["id"] for it in items} == latest | {first[0]["id"]}  # der andere fällt weg
    assert service.summary(pid)["pool"] == len(items)

    service.delete_query(q["id"])
    left = service.pool(pid)["items"]
    assert [it["id"] for it in left] == [first[0]["id"]] and left[0]["stale"]  # nur der schon entschiedene
    assert service.pool(pid)["stale"] == 1 and service.queue(pid, "open")["items"] == []

    with pytest.raises(ResearchError):
        service.reset_pool(pid)
    r = service.reset_pool(pid, confirm=True)
    assert r == {"deleted": 2, "decisions": 1} and service.pool(pid)["total"] == 0
    assert service.store.q("SELECT COUNT(*) FROM run WHERE project_id = ?", (pid,))[0][0] == 2  # Protokoll der Läufe bleibt


def test_more_folders_and_move(service, sim):
    """Mehr als sechs Ordner; vor dem Löschen werden aufgenommene Treffer verschoben (rückgängig als Ganzes)."""
    import pytest

    from zotllm.research.errors import ResearchError

    pid = make_project(service)["id"]
    service.update_project(pid, {"folder_map": [{"slot": 1, "label": "Teasing", "path": "T"}, {"slot": 12, "label": "Neu", "path": "N"},
                                                {"slot": 21, "label": "zu viel", "path": "X"}]})
    assert [f["slot"] for f in service.get_project(pid)["folder_map"]] == [1, 12]  # höchstens 20
    q = service.add_query(pid, "T2_Teasing", "pubmed", "teasing[tiab]")
    service.run_query(q["id"])
    a, b = [it["id"] for it in service.pool(pid)["items"]]
    service.decide(pid, a, "include", 12)
    service.decide(pid, b, "include", 12)
    assert service.summary(pid)["by_folder"] == {"12": 2}
    with pytest.raises(ResearchError):
        service.decide(pid, a, "include", 21)
    r = service.move_folder(pid, 12, 1)
    assert r["moved"] == 2 and service.summary(pid)["by_folder"] == {"1": 2}
    assert service.store.current_decision(pid, a)["method"] == "card"  # Entscheidweise bleibt
    assert service.undo(pid)["count"] == 2 and service.summary(pid)["by_folder"] == {"12": 2}
    with pytest.raises(ResearchError):
        service.move_folder(pid, 1, 1)
