"""Das Modul „Recherche“ im Server von Zotivity: Sicherheit (Host-Prüfung, X-Zotivity) und der ganze Ablauf über
/api/research/… (ohne Netz, Zotero als Attrappe)."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from research_fakes import QUERIES

from zotivity import __version__
from zotivity.server.app import create_app

H = {"X-Zotivity": "1"}


@pytest.fixture
def client(zengine, service):
    return TestClient(create_app(zengine, research=service))


def test_guard(client):
    assert client.get("/api/research/projects").status_code == 200
    assert client.post("/api/research/projects", json={"title": "x"}).status_code == 403  # ohne Header
    assert client.post("/api/research/projects", json={"title": "x"}, headers={"X-Litsearch": "1"}).status_code == 403
    assert client.get("/api/research/projects", headers={"host": "evil.example"}).status_code == 403
    index = client.get("/")
    assert index.status_code == 200 and f'"/static/v{__version__}/css/research.css"' in index.text
    assert client.get(f"/static/v{__version__}/js/views/research.js").status_code == 200
    assert client.get("/static/js/views/research/screening.js").status_code == 200


def test_errors_are_json(client):
    r = client.get("/api/research/projects/999")
    assert r.status_code == 404 and r.json()["kind"] == "not_found"
    pid = client.post("/api/research/projects", json={"title": "x"}, headers=H).json()["id"]
    r = client.post(f"/api/research/projects/{pid}/queries", json={"name": "a", "source": "psycinfo", "string": "x"}, headers=H)
    qid = r.json()["id"]
    r = client.post(f"/api/research/queries/{qid}/run", json={}, headers=H)
    assert r.status_code == 400 and r.json()["kind"] == "not_live"


def test_full_flow(client, zotero, sim):
    p = client.post("/api/research/projects", headers=H, json={
        "title": "Jugendliche und Onlineaggressionen", "target_library": "groups/4755508", "target_name": "Gruppe",
        "criteria_out": "Cyberbullying", "folder_map": [{"slot": 1, "label": "Teasing", "path": "(Cyber-) Teasing und Ostracism/neu"}]}).json()
    pid = p["id"]
    assert p["folder_map"][0]["path"] == "(Cyber-) Teasing und Ostracism/neu"

    blocks = [{"name": "Population", "terms": ["adolescen*", "teen*"]}, {"name": "Teasing", "terms": ["teasing", "banter"]}]
    assert client.put(f"/api/research/projects/{pid}/blocks", headers=H, json={"blocks": blocks}).status_code == 200
    built = client.post(f"/api/research/projects/{pid}/build", headers=H, json={}).json()
    assert built["pubmed"]["string"] == "(adolescen*[tiab] OR teen*[tiab]) AND (teasing[tiab] OR banter[tiab])"
    assert client.post("/api/research/count", headers=H, json={"source": "pubmed", "string": built["pubmed"]["string"]}).json()["count"] == 2

    files = [{"filename": "T2_Teasing.txt", "content_b64": base64.b64encode(b"teasing[tiab] AND teen*[tiab]").decode()}]
    qs = client.post(f"/api/research/projects/{pid}/queries/import", headers=H, json={"files": files, "source": "pubmed"}).json()["queries"]
    qid = qs[0]["id"]
    assert client.post(f"/api/research/queries/{qid}/count", headers=H).json()["last_count"] == 2
    run = client.post(f"/api/research/queries/{qid}/run", headers=H, json={}).json()
    assert run["new"] == 2

    tr = client.post("/api/research/translate", headers=H, json={"string": "teasing[tiab] AND teen*[tiab]"}).json()
    assert tr["string"] == "teasing AND teen"
    oq = client.post(f"/api/research/projects/{pid}/queries", headers=H, json={"name": "T2_Teasing", "source": "openalex", "string": tr["string"]}).json()
    assert client.post(f"/api/research/queries/{oq['id']}/run", headers=H, json={}).json()["duplicates"] == 1

    from test_research_sources import OVID
    imp = client.post(f"/api/research/projects/{pid}/import", headers=H, json={
        "filename": "ovid.ris", "content_b64": base64.b64encode(OVID.encode("cp1252")).decode(), "source": "psycinfo", "hits": 2}).json()
    assert imp["new"] == 2

    queries = client.get(f"/api/research/projects/{pid}/queries").json()["queries"]
    assert {(q["source"], q["current_run"]) for q in queries} == {("pubmed", True), ("openalex", True)}
    summary = client.get(f"/api/research/projects/{pid}/summary").json()
    assert summary["pool"] == 5 and summary["sources"] == {"pubmed": 2, "openalex": 2, "psycinfo": 2}

    pool = client.get(f"/api/research/projects/{pid}/pool?source=openalex").json()
    assert len(pool["items"]) == 2 and pool["total"] == 5
    assert len(client.get(f"/api/research/projects/{pid}/pool?text=bystander*").json()["items"]) == 1

    queue = client.get(f"/api/research/projects/{pid}/screening").json()
    first = queue["items"][0]["id"]
    d = client.post(f"/api/research/projects/{pid}/decisions", headers=H, json={"record_id": first, "status": "include", "folder": 1}).json()
    assert d["status"] == "include" and d["by"] == "Test"
    assert client.post(f"/api/research/projects/{pid}/decisions", headers=H, json={"record_id": first, "status": "include"}).status_code == 400
    client.post(f"/api/research/projects/{pid}/decisions", headers=H, json={"record_id": queue["items"][1]["id"], "status": "exclude", "reason": "Cyberbullying"})
    assert client.post(f"/api/research/projects/{pid}/decisions/undo", headers=H).json()["undone"]["status"] == "exclude"

    plan = client.get(f"/api/research/projects/{pid}/export/zotero").json()
    assert plan["library"] == "groups/4755508" and plan["totals"]["new"] == 1
    r = client.post(f"/api/research/projects/{pid}/export/zotero", headers=H, json={})
    assert r.status_code == 409 and zotero.writes == []  # ohne confirm nichts geschrieben
    res = client.post(f"/api/research/projects/{pid}/export/zotero", headers=H, json={"confirm": True, "crossref": False}).json()
    assert res["created"] == 1 and zotero.writes[0] == ("collection", "groups/4755508", "(Cyber-) Teasing und Ostracism", None)

    md = client.get(f"/api/research/projects/{pid}/protocol?kind=md")
    assert md.headers["x-filename"].endswith(".md") and "## Übergabe an Zotero" in md.text
    csv = client.get(f"/api/research/projects/{pid}/protocol?kind=runs")
    assert csv.headers["content-type"].startswith("text/csv")

    assert client.delete(f"/api/research/projects/{pid}", headers=H).json() == {"ok": True}
    assert client.get("/api/research/projects").json()["projects"] == []


def test_phase2a_endpoints(client, sim):
    info = client.get("/api/research/info").json()
    assert {"openalex", "eric", "psycinfo", "scholar"} <= {s["id"] for s in info["catalog"]}
    assert info["disciplines"]["edu"] == "Erziehungswissenschaft" and "europepmc" in info["translatable"]
    assert "eric" in client.get("/api/research/sources/suggest?disciplines=edu").json()["sources"]

    p = client.post("/api/research/projects", headers=H, json={"title": "Grenzfälle", "settings": {"sources": ["pubmed", "eric", "nix"]}}).json()
    pid = p["id"]
    assert p["settings"]["sources"] == ["pubmed", "eric"]
    p = client.put(f"/api/research/projects/{pid}", headers=H, json={"settings": {"disciplines": ["edu"]}}).json()
    assert p["settings"]["sources"] == ["pubmed", "eric"] and p["settings"]["disciplines"] == ["edu"]  # zusammengeführt

    q = client.post(f"/api/research/projects/{pid}/queries", headers=H, json={"name": "T2", "source": "pubmed",
                                                                            "string": "teasing[tiab] AND teen*[tiab]"}).json()
    out = client.post(f"/api/research/queries/{q['id']}/translate", headers=H, json={"targets": ["eric", "osf", "pubmed"]}).json()["queries"]
    assert [(x["source"], x["name"]) for x in out] == [("eric", "T2"), ("osf", "T2")]
    assert out[1]["string"] == "teasing teen" and out[1]["note"].startswith("übersetzt aus PubMed v1")
    terms = client.get(f"/api/research/projects/{pid}/terms").json()
    assert terms["queries"][0] == {"name": "T2", "terms": ["teasing", "teen*"]}

    rule = {"kind": "title", "pattern": "bully*", "exceptions": "banter", "active": True}
    client.put(f"/api/research/projects/{pid}", headers=H, json={"prefilters": [rule]})
    run = client.post(f"/api/research/queries/{q['id']}/run", headers=H, json={}).json()
    assert run["new"] == 2
    store = client.app.state.research.store
    run_id = store.add_run(pid, kind="import", source="ris")
    store.add_records(pid, run_id, [{"title": "Cyberbullying and banter online", "doi": "10.5555/b"},
                                    {"title": "Cyberbullying prevalence in schools", "doi": "10.5555/c"}])
    pool = client.get(f"/api/research/projects/{pid}/pool?status=hidden").json()
    assert [it["title"] for it in pool["items"]] == ["Cyberbullying prevalence in schools"]
    rule_id = pool["prefilters"][0]["id"]
    assert pool["prefilters"][0]["exception"] == 1 and pool["abstracts_open"] == 4  # auch die kurzen PubMed-Abstracts der Attrappe
    hidden_id = pool["items"][0]["id"]
    r = client.post(f"/api/research/projects/{pid}/review", headers=H, json={"record_ids": [hidden_id], "verdict": "borderline", "rule_id": rule_id})
    assert r.json() == {"reviewed": 1, "verdict": "borderline"}
    queue = client.get(f"/api/research/projects/{pid}/screening?status=borderline").json()
    assert [it["title"] for it in queue["items"]] == ["Cyberbullying prevalence in schools", "Cyberbullying and banter online"]
    other = queue["items"][1]["id"]
    assert client.post(f"/api/research/projects/{pid}/borderline", headers=H, json={"record_id": other, "reason": "Spass"}).json()["borderline"] == 1
    d = client.post(f"/api/research/projects/{pid}/decisions", headers=H, json={"record_id": other, "status": "include", "folder": 1}).json()
    assert d["borderline"] == 1 and d["borderline_reason"] == "Spass"
    rec = client.put(f"/api/research/projects/{pid}/key-papers", headers=H, json={"text": "10.5555/b, 10.5555/zz"}).json()
    assert rec["warnings"] == 1 and client.get(f"/api/research/projects/{pid}/recall").json()["papers"][0]["status"] == "include"
    ab = client.post(f"/api/research/projects/{pid}/abstracts", headers=H, json={"limit": 50}).json()
    assert ab["checked"] == 4 and ab["remaining"] == 0


def test_zotero_endpoints(client):
    assert client.get("/api/research/zotero/status?backend=web").json()["ok"] is True
    libs = client.get("/api/research/zotero/libraries?backend=web").json()["libraries"]
    assert libs[1]["lib"] == "groups/4755508"
    assert client.get("/api/research/zotero/status?backend=none").status_code == 400


@pytest.mark.skipif(not QUERIES.exists(), reason="Suchstrings des Projekts nicht vorhanden")
def test_project_query_files(client):
    """Die echten Suchstrings des Projekts Onlineaggression (Ordner in ZOTIVITY_TEST_QUERIES) lassen sich laden (nur lesen)."""
    pid = client.post("/api/research/projects", headers=H, json={"title": "Onlineaggression"}).json()["id"]
    files = [{"filename": f.name, "content_b64": base64.b64encode(f.read_bytes()).decode()} for f in sorted(QUERIES.glob("*.txt"))]
    qs = client.post(f"/api/research/projects/{pid}/queries/import", headers=H, json={"files": files}).json()["queries"]
    assert [q["name"] for q in qs] == ["D1_Deeskalation", "E1_Empathie", "I1_Interventionen", "K1_Konflikt", "R1_Rollen",
                                       "T1_Ostracism", "T2_Teasing"]
    assert all("\n" not in q["string"] and q["string"].endswith("NOT (cyberbully*[ti] OR cyber-bully*[ti])") for q in qs)
