"""Länge des Forschungsstands: verbindliche Obergrenze je Abschnitt, Ausgleich nach zu langen Abschnitten, Prüfung auf
zu lange Abschnitte und „Kürzen“ (Anlass: 1600 Wörter geplant, rund 2400 geschrieben)."""

from fastapi.testclient import TestClient

from zotivity.jobs import Job
from zotivity.rag.review import count_words, section_budget
from test_truncation import H, Scripted, service

LONG = "## Einleitung\n\n" + "Jugendliche nutzen Chatbots häufig und vielfältig. " * 30 + "[@A, S. 2]."
SHORT = "## Einleitung\n\nJugendliche nutzen Chatbots häufig [@A, S. 2]."


def make_review(zengine, sections=None):
    outline = {"title": "T", "sections": [
        {"heading": "Einleitung", "focus": "Gegenstand", "keys": [], "words": 100},
        {"heading": "Befunde", "focus": "Motive", "keys": [], "words": 100}]}
    state = {"outline": outline, "target_words": 200}
    if sections:
        state["sections"] = sections
    return zengine.store.create_review("T", "Wie nutzen Jugendliche Chatbots?", state)


def test_section_budget():
    plan = [330, 400, 400, 300, 170]
    assert section_budget(plan, 0, []) == 330
    # erster Abschnitt 138 Wörter zu lang: der zweite trägt seinen Anteil (400 von 1270) an der Überschreitung
    assert section_budget(plan, 1, [468]) == 357
    assert section_budget(plan, 1, [300]) == 400  # kürzere gleichen nicht nach oben aus
    assert section_budget([100, 100], 1, [400]) == 60  # höchstens bis auf 60 % des Plans
    assert section_budget([None, 100], 0, []) == 500  # ohne Plan wie bisher 500


def test_write_prompt_sets_binding_limit_and_balances(zengine):
    model = Scripted(lambda p, params: (LONG, "STOP") if "Abschnitt „Einleitung“" in p
                     else ("## Befunde\n\nKurz [@A].", "STOP"))
    svc = service(zengine, model)
    rid = make_review(zengine)
    svc.write(Job("review", "t"), rid)
    first, second = (c[0] for c in model.calls)
    assert "Umfang: 80–100 Wörter, Überschrift und Belege eingerechnet." in first and "verbindlich" in first
    assert "bisherigen Abschnitte" not in first
    # Einleitung ~200 statt 100 Wörter: die Befunde bekommen nur noch 60 (Untergrenze) und den Stand mitgeteilt
    assert "Umfang: 48–60 Wörter" in second
    assert f"Die bisherigen Abschnitte haben {count_words(LONG)} Wörter; für den ganzen Text sind etwa 200" in second

    check = svc.get(rid)["state"]["check"]
    assert check["planned_words"] == 200 and check["words"] == count_words(LONG) + 4
    assert check["long_sections"] == [{"index": 0, "heading": "Einleitung", "words": count_words(LONG), "planned": 100}]


def test_shorten_long_sections(zengine):
    rid = make_review(zengine, [{"heading": "Einleitung", "text": LONG},
                                {"heading": "Befunde", "text": "## Befunde\n\nKurz [@A]."}])
    # Das Modell lässt die Überschrift weg – sie kommt wieder davor
    model = Scripted(lambda p, params: ("Jugendliche nutzen Chatbots häufig [@A, S. 2].", "STOP"))
    svc = service(zengine, model)
    job = Job("review", "t")
    out = svc.shorten(job, rid)
    prompt = model.calls[0][0]
    assert len(model.calls) == 1 and f"von {count_words(LONG)} auf höchstens 100 Wörter" in prompt and LONG in prompt
    secs = svc.get(rid)["state"]["sections"]
    assert secs[0]["text"] == SHORT and secs[1]["text"] == "## Befunde\n\nKurz [@A]."
    assert out["sections"] == 1 and out["check"]["long_sections"] == []
    assert job.message == f"Gekürzt: {count_words(LONG)} → {count_words(SHORT)} Wörter"

    # Wird die Antwort nicht kürzer (oder bricht ab), bleibt der Abschnitt, wie er war
    zengine.store.update_review_state(rid, {**svc.get(rid)["state"], "sections": [{"heading": "Einleitung", "text": LONG}]})
    model.fn = lambda p, params: (LONG + " Noch mehr.", "STOP")
    job = Job("review", "t")
    out = svc.shorten(job, rid, [0])
    assert out["kept"] == ["Einleitung"] and svc.get(rid)["state"]["sections"][0]["text"] == LONG
    assert job.message.endswith("unverändert: Einleitung")


def test_shorten_api(zengine, monkeypatch):
    rid = make_review(zengine, [{"heading": "Einleitung", "text": SHORT}])
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        r = c.post(f"/api/reviews/{rid}/shorten", headers=H, json={})
        assert r.status_code == 400 and "länger als geplant" in r.text
        assert c.post(f"/api/reviews/{rid}/shorten", headers=H, json={"sections": ["x"]}).status_code == 400
        assert c.get(f"/api/reviews/{rid}", headers=H).json()["state"].get("check") is None
