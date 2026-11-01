"""Projekte, Export/Import, Presets, Suchstrategie, Relevanzanzeige, Kostenschätzung."""

import json
import re

from fakes import ScriptedModel
from test_rag import indexed, install_models  # noqa: F401 - Fixture
from test_server import H, client  # noqa: F401 - Fixture

from zotivity.jobs import Job
from zotivity.rag import ReviewService


def wait(client, job):
    import time

    for _ in range(200):
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.05)
    raise AssertionError("Auftrag endet nicht")


# ---------------------------------------------------------------------------------- Projekte
def test_project_lifecycle(client):
    [default] = client.get("/api/projects").json()["projects"]
    assert default["name"] == "Allgemein"
    p = client.post("/api/projects", json={"name": "KI und Jugend", "description": "Test"}, headers=H).json()
    assert client.post("/api/projects", json={"name": "ki und jugend"}, headers=H).status_code == 409
    cid = client.post("/api/corpora", json={"name": "Chatbots", "sources": ["users/0:COLA0001"],
                                            "project_id": p["id"]}, headers=H).json()["id"]
    assert client.get("/api/projects").json()["projects"][1]["corpus_ids"] == [cid]
    # Ein Korpus kann in mehreren Projekten sein
    client.put(f"/api/projects/{default['id']}/corpora/{cid}", json={"assigned": True}, headers=H)
    corpus = next(c for c in client.get("/api/corpora").json()["corpora"] if c["id"] == cid)
    assert sorted(corpus["project_ids"]) == sorted([p["id"], default["id"]])
    # Öffnen ändert die Reihenfolge nicht (keine springenden Kacheln), merkt sich aber das aktive Projekt
    client.post(f"/api/projects/{default['id']}/open", headers=H)
    assert [x["id"] for x in client.get("/api/projects").json()["projects"]] == [default["id"], p["id"]]
    assert client.app.state.engine.active_project_id() == default["id"]
    # Chats gehören zum Projekt
    client.post("/api/chat", json={"question": "Chatbots", "search_only": True, "project_id": p["id"],
                                   "filters": {"project_id": p["id"]}}, headers=H)
    assert len(client.get(f"/api/chats?project={p['id']}").json()["chats"]) == 1
    assert client.get(f"/api/chats?project={default['id']}").json()["chats"] == []
    # Löschen: Korpus bleibt, weil er auch im anderen Projekt ist
    r = client.delete(f"/api/projects/{p['id']}?delete_corpora=true", headers=H).json()
    assert r["corpora_deleted"] == 0 and any(c["id"] == cid for c in client.get("/api/corpora").json()["corpora"])
    assert client.delete(f"/api/projects/{default['id']}", headers=H).status_code == 400  # letztes Projekt


def test_project_archive(client):
    [default] = client.get("/api/projects").json()["projects"]
    # Das einzige offene Projekt lässt sich nicht archivieren
    assert client.post(f"/api/projects/{default['id']}/archive", json={}, headers=H).status_code == 400
    p = client.post("/api/projects", json={"name": "Altlast"}, headers=H).json()
    client.post(f"/api/projects/{p['id']}/open", headers=H)
    a = client.post(f"/api/projects/{p['id']}/archive", json={"archived": True}, headers=H).json()
    assert a["archived_at"]
    # Archiviert: bleibt erhalten, ist aber nicht mehr zu öffnen und nicht mehr das aktive Projekt
    assert len(client.get("/api/projects").json()["projects"]) == 2
    assert client.post(f"/api/projects/{p['id']}/open", headers=H).status_code == 400
    assert client.app.state.engine.active_project_id() == default["id"]
    # Das offene Projekt ist jetzt das letzte – weder archivieren noch löschen
    assert client.post(f"/api/projects/{default['id']}/archive", json={}, headers=H).status_code == 400
    assert client.delete(f"/api/projects/{default['id']}", headers=H).status_code == 400
    # Zurückholen
    r = client.post(f"/api/projects/{p['id']}/archive", json={"archived": False}, headers=H).json()
    assert r["archived_at"] is None
    assert client.post(f"/api/projects/{p['id']}/open", headers=H).status_code == 200


def test_project_order_by_hand(client):
    a = client.get("/api/projects").json()["projects"][0]["id"]
    b = client.post("/api/projects", json={"name": "B"}, headers=H).json()["id"]
    c = client.post("/api/projects", json={"name": "C"}, headers=H).json()["id"]

    def order():
        return [p["id"] for p in client.get("/api/projects").json()["projects"]]

    assert order() == [a, b, c]
    r = client.post("/api/projects/reorder", json={"ids": [c, a, b]}, headers=H)
    assert [p["id"] for p in r.json()["projects"]] == [c, a, b] and order() == [c, a, b]
    # Öffnen ändert die Reihenfolge nicht; neue Projekte kommen ans Ende
    client.post(f"/api/projects/{b}/open", headers=H)
    d = client.post("/api/projects", json={"name": "D"}, headers=H).json()["id"]
    assert order() == [c, a, b, d]
    for bad in ([], [a, a], [a, 9999]):
        assert client.post("/api/projects/reorder", json={"ids": bad}, headers=H).status_code == 400


def test_search_history_per_project(client):
    projects = client.get("/api/projects").json()["projects"]
    a = projects[0]["id"]
    b = client.post("/api/projects", json={"name": "Zweites"}, headers=H).json()["id"]

    def search(pid, **q):
        return client.post("/api/library/search", json={"query": q, "project_id": pid}, headers=H).json()

    r = search(a, q="chatbots")
    assert r["searches"][0]["query"] == {"q": "chatbots"} and r["searches"][0]["total"] == 1
    search(a, creator="devlieghere", year_from=2010, item_types=["journalArticle"])
    search(a, q="  chatbots ", sort="year_desc")  # gleiche Suche: rückt nach oben, kein zweiter Eintrag
    hist = client.get(f"/api/library/searches?project={a}").json()["searches"]
    assert [h["query"] for h in hist] == [{"q": "chatbots"},
                                         {"creator": "devlieghere", "year_from": 2010, "item_types": ["journalArticle"]}]
    assert hist[0]["sort"] == "year_desc"
    # „Weitere laden“ (offset) zählt nicht als neue Suche; ohne Projekt wird nichts gespeichert
    client.post("/api/library/search", json={"query": {"q": "jugend", "offset": 100}, "project_id": a}, headers=H)
    client.post("/api/library/search", json={"query": {"q": "jugend"}}, headers=H)
    assert len(client.get(f"/api/library/searches?project={a}").json()["searches"]) == 2
    # Je Projekt getrennt
    assert client.get(f"/api/library/searches?project={b}").json()["searches"] == []
    search(b, q="systems")
    assert len(client.get(f"/api/library/searches?project={b}").json()["searches"]) == 1
    # Eine Suche entfernen, dann alle
    left = client.delete(f"/api/library/searches?project={a}&id={hist[0]['id']}", headers=H).json()["searches"]
    assert [h["id"] for h in left] == [hist[1]["id"]]
    assert client.delete(f"/api/library/searches?project={a}", headers=H).json()["searches"] == []
    assert len(client.get(f"/api/library/searches?project={b}").json()["searches"]) == 1
    # Löschen des Projekts entfernt seinen Verlauf
    client.delete(f"/api/projects/{b}", headers=H)
    assert client.app.state.engine.store.searches(b) == []


def test_project_export_import_roundtrip(client):
    p = client.post("/api/projects", json={"name": "Export"}, headers=H).json()
    cid = client.post("/api/corpora", json={"name": "Alles A", "sources": ["users/0:COLA0001"],
                                            "project_id": p["id"]}, headers=H).json()["id"]
    client.post("/api/chat", json={"question": "Chatbots Jugendliche", "search_only": True, "project_id": p["id"]},
                headers=H)
    client.post("/api/library/search", json={"query": {"q": "chatbots"}, "project_id": p["id"]}, headers=H)
    r = client.get(f"/api/projects/{p['id']}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    imported = client.post("/api/projects/import", content=r.content, headers=H).json()
    assert imported["name"] == "Export (2)" and imported["corpora_reused"] == 1 and imported["chats"] == 1
    assert imported["missing_sources"] == [] and imported["checked"] is True
    new = next(x for x in client.get("/api/projects").json()["projects"] if x["id"] == imported["project_id"])
    assert new["corpus_ids"] == [cid] and new["chats"] == 1
    [s] = client.get(f"/api/library/searches?project={new['id']}").json()["searches"]  # Suchverlauf kommt mit
    assert s["query"] == {"q": "chatbots"} and s["total"] == 1
    bad =client.post("/api/projects/import", content=b"kein zip", headers=H)
    assert bad.status_code == 400 and "zllm" in bad.json()["detail"]


# ---------------------------------------------------------------------------------- Presets
def test_presets(client):
    data = client.get("/api/presets").json()
    assert {p["id"] for p in data["presets"]} >= {"schnell", "ausgewogen", "gruendlich", "wortgenau"}
    assert data["active"] == "ausgewogen" and data["changed"] == []
    data = client.post("/api/presets/apply", json={"id": "gruendlich"}, headers=H).json()
    s = client.get("/api/settings").json()
    assert s["retrieval"]["top_k"] == 30 and s["llm"]["effort"] == "high" and data["changed"] == []
    client.put("/api/settings", json={"retrieval": {"top_k": 22}}, headers=H)
    changed = client.get("/api/presets").json()["changed"]
    assert changed == [{"field": "retrieval.top_k", "preset": 30, "current": 22}]
    data = client.post("/api/presets", json={"label": "Mein Seminar"}, headers=H).json()
    assert data["active"] == "mein-seminar" and data["changed"] == []
    assert client.post("/api/presets", json={"label": "X", "values": {"retrieval.top_k": 9999}},
                       headers=H).status_code == 400
    assert client.delete("/api/presets/gruendlich", headers=H).status_code == 404  # eingebaut
    data = client.request("DELETE", "/api/presets/mein-seminar", headers=H).json()
    assert data["active"] == "ausgewogen"


# ---------------------------------------------------------------------------------- Relevanz
def test_sources_carry_relevance(client):
    sources = client.post("/api/search", json={"query": "Chatbots Jugendliche"}, headers=H).json()["sources"]
    top = sources[0]["relevance"]
    assert top["level"] == 5 and top["label"] == "sehr hoch" and top["rank"] == 1 and top["of"] == len(sources)
    assert top["basis"] in ("vector", "keyword") and all(1 <= s["relevance"]["level"] <= 5 for s in sources)


# ---------------------------------------------------------------------------------- Forschungsstand
def test_strategy_title_stats_and_method(indexed, monkeypatch):  # noqa: F811
    def screen(prompt):
        keys = re.findall(r"\[([A-Z0-9]{8})\]", prompt)
        return json.dumps({"decisions": [{"key": k, "decision": "include", "reason": "passt"} for k in keys]})

    helper = ScriptedModel([
        ("möglichst ALLE relevanten Texte", json.dumps({"title": "Chatbots bei Jugendlichen",
                                                        "queries": ["Chatbots Jugendliche", "information systems"]})),
        ("Entscheide für jeden Text", screen),
    ])
    install_models(monkeypatch, helper, ScriptedModel([]))
    svc = ReviewService(indexed)
    question = ("Wie nutzen Jugendliche Chatbots bei persönlichen Problemen, und welche Folgen für Beratung "
                "und Soziale Arbeit werden in der Literatur beschrieben?")
    rid = svc.create("", question)
    assert svc.get(rid)["title"] == question  # vorläufig die ganze Frage, nichts abgeschnitten
    svc.generate_strategy(Job("review", "t"), rid)
    r = svc.get(rid)
    assert r["title"] == "Chatbots bei Jugendlichen" and r["state"]["step"] == "strategy"
    assert r["state"]["queries"] == [question, "Chatbots Jugendliche", "information systems"]
    # Bearbeiten: eigene Anfrage ergänzen, eine entfernen
    svc.set_strategy(rid, ["Chatbots Jugendliche", "information systems", "  ", "chatbots jugendliche"])
    assert svc.get(rid)["state"]["queries"] == ["Chatbots Jugendliche", "information systems"]
    # Nur Stichwortsuche: in der Mini-Bibliothek findet sonst jede Anfrage alle Texte
    indexed.settings_store.update({"retrieval": {"hybrid_weight": 0.0}})
    svc.find_candidates(Job("review", "t"), rid)
    stats = {s["query"]: s for s in svc.get(rid)["state"]["query_stats"]}
    assert stats["Chatbots Jugendliche"] == {"query": "Chatbots Jugendliche", "docs": 1, "unique": 1}
    assert stats["information systems"] == {"query": "information systems", "docs": 1, "unique": 1}
    appendix = svc.method_appendix(indexed.store.get_review(rid))
    assert "Methode der Literatursuche" in appendix and "| information systems |" in appendix
    # Eigener Titel bleibt beim erneuten Vorschlag erhalten
    svc.set_title(rid, "Mein Titel")
    svc.generate_strategy(Job("review", "t"), rid)
    assert svc.get(rid)["title"] == "Mein Titel"


def test_extraction_estimate_with_prices(indexed, monkeypatch):  # noqa: F811
    svc = ReviewService(indexed)
    rid = svc.create("T", "Frage")
    indexed.store.put_review_docs(rid, [{"lib": "users/0", "item_key": "ITEMA001", "included": True}])
    est = svc.estimate_extraction(rid)
    assert est["output_tokens"] == [800, 1500] and est["cost"] is None
    model = est["model"]
    indexed.settings_store.update({"llm": {"prices": {model: [3.0, 15.0]}, "effort": "high"},
                                   "review": {"sheet_model": "main"}})
    est = svc.estimate_extraction(rid)
    assert est["thinking_tokens"] == [1600, 7500] and est["cost"][0] < est["cost"][1]
