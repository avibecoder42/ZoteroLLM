"""Abgebrochene Ausgaben der Sprachmodelle: erkennen, einmal neu versuchen, unvollständige Abschnitte melden und einzeln
neu schreiben (Anlass: Gemini brach einen Abschnitt mitten in einem wörtlichen Zitat ab)."""

import json

from fastapi.testclient import TestClient

from zotivity.jobs import Job
from zotivity.llm import ChatModel, GenParams, StreamEvent, Usage, truncation
from zotivity.llm.base import RECITATION_HINT
from zotivity.rag import ReviewService
from zotivity.rag.review import incomplete_reasons, unclosed_quote

H = {"X-Zotivity": "1"}
CUT = ("In einer Querschnittstudie beschrieben Samatha et al. diese Wirkungsweise prägnant: „These results suggest "
       "that AI tools are perceived by adolescents as emotionally neutral yet cognitively supportive companions, useful")


class Scripted(ChatModel):
    """Antwort und Stoppgrund je Aufruf aus einer Funktion (prompt, params) → (text, stop_reason)."""

    provider = "fake"

    def __init__(self, fn):
        super().__init__("fake-model")
        self.fn = fn
        self.calls: list[tuple[str, GenParams]] = []

    def _stream(self, system, messages, params):
        prompt = "\n".join(m.content for m in messages)
        self.calls.append((prompt, params))
        text, stop = self.fn(prompt, params)
        yield StreamEvent("text", text=text)
        yield StreamEvent("done", usage=Usage(1, 1, 0, 1), stop_reason=stop, model=self.model)


def test_truncation_kinds():
    assert truncation("MAX_TOKENS") == truncation("max_tokens") == truncation("length") == "length"
    assert truncation("RECITATION") == "recitation"
    assert truncation("STOP") == truncation("end_turn") == truncation("stop") == truncation("") == ""


def test_complete_json_retries_after_truncation():
    full = json.dumps({"kernzitate": [{"zitat": "kurz", "seite": "3"}]})
    m = Scripted(lambda p, params: (full, "STOP") if RECITATION_HINT in p else (full[:20], "RECITATION"))
    assert m.complete_json("", "Blatt bitte") == {"kernzitate": [{"zitat": "kurz", "seite": "3"}]}
    assert len(m.calls) == 2 and RECITATION_HINT in m.calls[1][0]

    m = Scripted(lambda p, params: (full, "STOP") if params.max_tokens > 8000 else (full[:20], "MAX_TOKENS"))
    m.complete_json("", "Blatt bitte", GenParams(max_tokens=8000))
    assert [c[1].max_tokens for c in m.calls] == [8000, 16000]


def test_incomplete_section_detection():
    assert unclosed_quote(CUT)
    assert not unclosed_quote("Sie schreiben „AI tools are useful“ [@A, S. 2].")
    assert not unclosed_quote("„Eins“ und „zwei“.")
    assert unclosed_quote("„Eins“ und „zwei.")
    assert incomplete_reasons({"text": f"## 3. Coping\n\n{CUT}"}, 333) == ["quote", "sentence", "short"]
    ok = "## Befunde\n\nJugendliche nutzen Chatbots [@ITEMA001, S. 3]."
    assert incomplete_reasons({"text": ok}, 1000) == []  # nur kürzer als geplant: kein Fehler
    assert incomplete_reasons({"text": "## Liste\n\n- erster Punkt\n- zweiter Punkt"}) == []
    assert incomplete_reasons({"text": ok, "stopped": "length"}) == ["stopped:length"]


def make_review(zengine):
    outline = {"title": "T", "sections": [
        {"heading": "Einleitung", "focus": "Gegenstand", "keys": [], "words": 100},
        {"heading": "Befunde", "focus": "Motive", "keys": [], "words": 100}]}
    return zengine.store.create_review("T", "Wie nutzen Jugendliche Chatbots?", {"outline": outline})


def service(zengine, model):
    svc = ReviewService(zengine)
    svc._model = lambda kind, job: (model, "")
    svc._sheets_block = lambda rid: ("", {})
    return svc


def test_write_retries_and_reports_incomplete_sections(zengine):
    def answer(prompt, params):
        if "Abschnitt „Einleitung“" in prompt:  # Wiedergabe-Sperre beim ersten Versuch, dann vollständig
            if RECITATION_HINT in prompt:
                return "## Einleitung\n\nSie seien „kognitiv unterstützend“ [@A, S. 2].", "STOP"
            return f"## Einleitung\n\n{CUT}", "RECITATION"
        return "## Befunde\n\nDie Befunde zeigen, dass Jugendliche", "MAX_TOKENS"  # bleibt abgeschnitten

    model = Scripted(answer)
    svc = service(zengine, model)
    rid = make_review(zengine)
    svc.write(Job("review", "t"), rid)
    secs = svc.get(rid)["state"]["sections"]
    assert "stopped" not in secs[0] and secs[0]["text"].endswith("[@A, S. 2].")
    assert secs[1]["stopped"] == "length"
    befunde = [c for c in model.calls if "Abschnitt „Befunde“" in c[0]]
    # zweiter Versuch mit mehr Platz: das eingestellte Maximum (mindestens doppelt so viel)
    assert [c[1].max_tokens for c in befunde] == [4400, max(8800, zengine.settings.llm.max_output_tokens)]
    check = svc.get(rid)["state"]["check"]
    assert [(x["index"], x["reasons"]) for x in check["incomplete_sections"]] == [
        (1, ["stopped:length", "sentence", "short"])]

    # Nur den abgeschnittenen Abschnitt neu schreiben – der andere bleibt unverändert
    model.fn = lambda p, params: ("## Befunde\n\nDie Befunde zeigen Entlastung [@A, S. 4].", "STOP")
    svc.rewrite_section(Job("review", "t"), rid, 1)
    secs2 = svc.get(rid)["state"]["sections"]
    assert secs2[0] == secs[0] and secs2[1]["text"].endswith("[@A, S. 4].") and "stopped" not in secs2[1]
    assert svc.get(rid)["state"]["check"]["incomplete_sections"] == []


def test_old_check_is_refreshed_and_rewrite_api(zengine, monkeypatch):
    rid = zengine.store.create_review("T", "Frage", {
        "outline": {"sections": [{"heading": "3. Coping", "words": 333}]},
        "sections": [{"heading": "3. Coping", "text": f"## 3. Coping\n\n{CUT}"}],
        "check": {"words": 30, "cited_docs": 0, "uncited_docs": [], "unknown_keys": [], "verified_quotes": 0,
                  "unverified_quotes": [], "checked_at": 0}})
    svc = ReviewService(zengine)
    inc = svc.get(rid)["state"]["check"]["incomplete_sections"]
    assert inc[0]["index"] == 0 and "quote" in inc[0]["reasons"]
    monkeypatch.setattr("zotivity.server.app.ollama_available", lambda url: False)
    from zotivity.server.app import create_app

    with TestClient(create_app(zengine)) as c:
        assert c.post(f"/api/reviews/{rid}/sections/5/rewrite", headers=H).status_code == 404
