"""KI-Vorschläge (Phase 2b) ohne Netz: Fachlogik mit einer Attrappe des ChatModel-Ports; der Adapter ResearchChat über
ZotLLMs Claude-Anbindung mit einer Attrappe des Anthropic-Clients."""

from __future__ import annotations

import re
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from research_fakes import MemoryKeyStore
from test_research_pool_screening import make_project

from zotllm.keystore import get_store
from zotllm.llm.anthropic_provider import _FALLBACK_BETA as FALLBACK_BETA
from zotllm.llm.anthropic_provider import AnthropicChat
from zotllm.research.ai import SCREENING_SCHEMA, estimate_cost
from zotllm.research_adapters import ResearchChat
from zotllm.settings import Settings
from zotllm.research.errors import ResearchError
from zotllm.research.service import ResearchService


class FakeChat:
    """ChatModel-Port: zeichnet Anfragen auf und antwortet über ``responder(system, prompt, schema)``."""

    label = "Claude (claude-test)"
    model = "claude-test"

    def __init__(self, responder):
        self.responder = responder
        self.calls = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0}

    def complete_json(self, system, prompt, schema=None):
        self.calls.append((system, prompt, schema))
        self.usage["requests"] += 1
        return self.responder(system, prompt, schema)


def ids_in(prompt):
    return [int(x) for x in re.findall(r"^id: (\d+)$", prompt, re.M)]


@pytest.fixture
def ai_service(store, sim, zotero):
    def responder(system, prompt, schema):
        ids = ids_in(prompt)
        items = [{"id": ids[0], "label": "passend", "folder": 2, "criterion": "alltägliche Onlineaggressionen",
                  "reason": "Untersucht Konflikte unter Jugendlichen online."}]
        if len(ids) > 1:
            items.append({"id": ids[1], "label": "grenzfall", "folder": 1, "criterion": "manifestes Cyberbullying",
                          "reason": "Grenze zwischen Spass und Cyberbullying."})
        if len(ids) > 2:
            items.append({"id": ids[2], "label": "vielleicht", "folder": 0, "criterion": "", "reason": "?"})
        items.append({"id": 99999, "label": "passend", "folder": 1, "criterion": "", "reason": "erfunden"})
        return {"items": items}

    chat = FakeChat(responder)
    svc = ResearchService(store, MemoryKeyStore(), {"web": zotero}, http=sim.http(), chat=chat, sleep=lambda s: None)
    return svc, chat


def pool(svc):
    pid = make_project(svc, question="Wie gehen Jugendliche mit Onlineaggressionen um?")["id"]
    run = svc.store.add_run(pid, kind="import", source="ris")
    svc.store.add_records(pid, run, [
        {"title": "Online conflict among adolescents in group chats", "abstract": "a" * 80, "doi": "10.5555/1"},
        {"title": "Banter or cyberbullying? Adolescents' views", "abstract": "", "doi": "10.5555/2"},
        {"title": "Neural correlates of exclusion in adults", "abstract": "c" * 80, "doi": "10.5555/3"},
    ])
    return pid


def test_ai_screen_stores_checked_suggestions(ai_service):
    svc, chat = ai_service
    pid = pool(svc)
    r = svc.ai_screen(pid)
    assert r["processed"] == 3 and r["remaining"] == 0 and r["counts"] == {"include": 1, "borderline": 1, "keine Antwort": 1}
    system, prompt, schema = chat.calls[0]
    assert schema == SCREENING_SCHEMA
    assert "Ausschlusskriterien:\n- manifestes Cyberbullying" not in system or "Cyberbullying" in system
    assert "2: Rollen" in system and "Fragestellung: Wie gehen Jugendliche" in system
    assert "(kein Abstract – nur Titel)" in prompt and "id: 99999" not in prompt
    ai = svc.store.ai_suggestions(pid)
    first, second, third = sorted(ai)
    assert ai[first]["label"] == "include" and ai[first]["folder"] == 2 and ai[first]["model"] == "claude-test"
    assert ai[second]["label"] == "borderline" and ai[second]["folder"] == 1
    assert ai[third]["label"] == ""  # ungültige Klasse: kein Vorschlag, aber auch kein endloses Nachfragen
    assert 99999 not in ai
    assert svc.ai_screen(pid)["processed"] == 0  # nichts mehr offen

    # Grenzfall-Vorschlag erscheint in der Grenzfall-Warteschlange (Quelle „KI“), entscheidet aber nichts
    q = svc.queue(pid, "borderline")
    assert [it["id"] for it in q["items"]] == [second] and q["items"][0]["borderline"][0]["where"] == "ai"
    assert [it["id"] for it in svc.queue(pid, "ai_include")["items"]] == [first]
    assert svc.queue(pid, "open")["ai_counts"] == {"include": 1, "borderline": 1, "none": 1}
    assert all(it["decision"] is None for it in svc.queue(pid, "all")["items"])

    d = svc.decide(pid, first, "include", 2)
    assert (d["ai_suggestion"], d["ai_reason"]) == ("include", "Untersucht Konflikte unter Jugendlichen online.")
    svc.decide(pid, second, "exclude", reason="manifestes Cyberbullying")
    md, _, _ = svc.protocol(pid, "md")
    assert "KI-gestützte Vorauswahl: 2 Vorschläge von claude-test" in md
    assert "Übereinstimmung bei „passend“/„nicht passend“: 1 von 1" in md and "| Grenzfall | 0 | 0 | 1 |" in md
    csv, _, _ = svc.protocol(pid, "records")
    assert "KI-Vorschlag;KI-Begründung" in csv and "passend;Untersucht Konflikte" in csv


def counts(scope):
    return {k: scope[k] for k in ("new", "failed", "done")}


def test_ai_redo_and_scope(ai_service):
    svc, chat = ai_service
    pid = pool(svc)
    svc.ai_screen(pid, limit=2)
    assert len(chat.calls) == 1 and svc.ai_screen(pid, limit=2)["processed"] == 1
    assert counts(svc.ai_plan(pid)["scopes"]["all"]) == {"new": 0, "failed": 0, "done": 3}

    def earlier():  # Vorschläge aus früheren Durchgängen
        with svc.store.tx() as db:
            db.execute("UPDATE ai_suggestion SET at = '2000-01-01T00:00:00'")

    earlier()
    r = svc.ai_screen(pid, limit=2, scope="all", redo="all")
    assert r["processed"] == 2 and r["remaining"] == 1
    r = svc.ai_screen(pid, limit=2, scope="all", redo="all", since=r["since"])
    assert r["processed"] == 1 and r["remaining"] == 0  # jeder Treffer einmal je Durchgang
    assert svc.ai_screen(pid, scope="all", redo="all", since=r["since"])["processed"] == 0

    earlier()
    svc.ai_screen(pid, scope="all", redo="all")  # ein Stapel zu 3: der dritte ohne gültige Antwort
    assert counts(svc.ai_plan(pid)["scopes"]["all"]) == {"new": 0, "failed": 1, "done": 2}
    earlier()
    r = svc.ai_screen(pid, scope="all", redo="failed")
    assert r["processed"] == 1 and r["remaining"] == 0  # nur der ohne gültige Antwort
    assert svc.ai_plan(pid)["scopes"]["all"]["failed"] == 0
    with pytest.raises(ResearchError):
        svc.ai_screen(pid, scope="alles")
    with pytest.raises(ResearchError):
        svc.ai_screen(pid, redo="immer")


def test_without_model(service):
    pid = pool(service)
    assert service.ai_status()["available"] is False and service.info()["ai"]["available"] is False
    with pytest.raises(ResearchError) as e:
        service.ai_screen(pid)
    assert e.value.kind == "ai_missing"


def test_ai_sources_only_from_catalog(store, sim, zotero):
    chat = FakeChat(lambda s, p, schema: {
        "disciplines": ["social", "psych", "astrologie"],
        "sources": [{"id": "openalex", "reason": "Breite Basis."}, {"id": "scholar", "reason": "verboten"},
                    {"id": "xyz", "reason": "gibt es nicht"}, {"id": "psycinfo", "reason": "Kernquelle Psychologie."},
                    {"id": "openalex", "reason": "doppelt"}],
        "note": "Graue Literatur über OpenAlex.",
    })
    svc = ResearchService(store, MemoryKeyStore(), {"web": zotero}, http=sim.http(), chat=chat)
    pid = svc.create_project({"title": "leer"})["id"]
    with pytest.raises(ResearchError):
        svc.ai_sources(pid)  # ohne Fragestellung kein Vorschlag
    svc.update_project(pid, {"question": "Wie gehen Jugendliche mit Onlineaggressionen um?"})
    r = svc.ai_sources(pid)
    assert r["disciplines"] == ["social", "psych"]
    assert [(s["id"], s["access"]) for s in r["sources"]] == [("openalex", "live"), ("psycinfo", "export")]
    system, prompt, schema = chat.calls[-1]
    assert "- psycinfo: APA PsycInfo" in system and "- scholar:" not in system
    assert "Fragestellung: Wie gehen Jugendliche" in prompt and "'scholar'" not in str(schema)
    assert svc.get_project(pid)["settings"]["sources"] == ["pubmed", "openalex"]  # nichts automatisch übernommen


def test_bulk_decisions_blind_and_undo(ai_service):
    svc, _ = ai_service
    pid = pool(svc)
    svc.ai_screen(pid)
    a, b, c = sorted(svc.store.ai_suggestions(pid))  # passend, Grenzfall, ohne gültige Antwort
    d = svc.decide(pid, a, "include", 2, ai_shown=False)
    assert (d["ai_shown"], d["method"], d["ai_suggestion"]) == (0, "card", "include")  # blind, Vorschlag trotzdem vermerkt
    r = svc.decide_bulk(pid, [{"record_id": b, "status": "exclude"}, {"record_id": c, "status": "include", "folder": 1}],
                        ai_shown=True)
    assert r["count"] == 2 and r["counts"] == {"exclude": 1, "include": 1}
    hist = svc.store.decision_history(pid)
    assert {h["batch"] for h in hist[-2:]} == {r["batch"]} and {h["method"] for h in hist[-2:]} == {"list"}
    assert [h["ai_shown"] for h in hist[-2:]] == [1, None]  # ohne gültigen Vorschlag gibt es nichts zu sehen

    md, _, _ = svc.protocol(pid, "md")
    assert "Entscheidweise: 1 einzeln auf Karten, 2 per Sammel-Übernahme aus der Liste" in md
    assert "KI-Vorschlag beim Entscheid sichtbar: 1; ausgeblendet (blind entschieden): 1. Davon per Sammel-Übernahme mit KI-Vorauswahl: 1." in md
    csv, _, _ = svc.protocol(pid, "records")
    assert "KI sichtbar;Entscheidweise" in csv

    u = svc.undo(pid)  # die ganze Sammel-Übernahme
    assert u["count"] == 2 and u["batch"] == r["batch"]
    assert svc.store.current_decision(pid, b) is None and svc.store.current_decision(pid, a)["status"] == "include"
    with pytest.raises(ResearchError):
        svc.decide_bulk(pid, [{"record_id": b, "status": "exclude"}, {"record_id": c, "status": "include"}])  # ohne Ordner
    assert svc.store.current_decision(pid, b) is None  # nichts halb gespeichert
    with pytest.raises(ResearchError):
        svc.decide_bulk(pid, [])
    assert svc.get_project(pid)["settings"]["ai_visible"] is True


def test_ai_blocks_checked_and_not_saved(store, sim, zotero):
    chat = FakeChat(lambda s, p, schema: {
        "blocks": [
            {"name": "Population", "kind": "include", "field": "tiab", "terms": ["adolescen*", '"young people"', "Adolescen*", ""],
             "mesh": ["Adolescent"], "psycinfo": [], "reason": "Jugendliche."},
            {"name": "population", "kind": "include", "field": "tiab", "terms": ["teen*"], "mesh": [], "psycinfo": [], "reason": "doppelt"},
            {"name": "Leer", "kind": "include", "field": "tiab", "terms": [], "mesh": [], "psycinfo": [], "reason": "ohne Begriffe"},
            {"name": "Tierstudien", "kind": "exclude", "field": "tiab", "terms": ["rat*", "mice"], "mesh": [], "psycinfo": [], "reason": "Tiere."},
            {"name": "Phänomen", "kind": "irgendwas", "field": "xy", "terms": ["cyberteas*", "online conflict"], "mesh": [],
             "psycinfo": ["Cyberbullying"], "reason": "Alltägliche Onlineaggression."},
        ],
        "note": "Deutschsprachige Begriffe fehlen.",
    })
    svc = ResearchService(store, MemoryKeyStore(), {"web": zotero}, http=sim.http(), chat=chat)
    pid = svc.create_project({"title": "leer"})["id"]
    with pytest.raises(ResearchError):
        svc.ai_blocks(pid)  # ohne Fragestellung kein Vorschlag
    svc.update_project(pid, {"question": "Wie gehen Jugendliche mit Onlineaggressionen um?"})
    r = svc.ai_blocks(pid, [{"name": "Population", "kind": "include", "terms": ["youth"], "mesh": [], "psycinfo": []}])
    assert [b["name"] for b in r["blocks"]] == ["Population", "Tierstudien", "Phänomen"]
    pop, animals, phen = r["blocks"]
    assert pop["terms"] == ["adolescen*", "young people"] and pop["mesh"] == ["Adolescent"]
    assert (animals["kind"], animals["field"]) == ("exclude", "ti")  # Ausschluss nie über Titel+Abstract
    assert (phen["kind"], phen["field"], phen["psycinfo"]) == ("include", "tiab", ["Cyberbullying"])
    assert r["note"] == "Deutschsprachige Begriffe fehlen." and r["available"] is True
    system, prompt, schema = chat.calls[-1]
    assert "Was mit NOT wegfällt" in system and "Fragestellung: Wie gehen Jugendliche" in prompt
    assert "Vorhandene Blöcke:\n- Population (Einschluss): youth" in prompt and schema["required"] == ["blocks", "note"]
    assert svc.store.blocks(pid) == []  # nichts gespeichert


# ------------------------------------------------------------------------------------------- Claude über ZotLLM
class FakeAnthropic:
    """Wie ``anthropic.Anthropic`` für ZotLLMs AnthropicChat: ``messages.stream`` bzw. ``beta.messages.stream`` als
    Kontextmanager; jede Anfrage bekommt die nächste Antwort (die letzte wiederholt sich)."""

    def __init__(self, *responses, error=None):
        self.calls = []
        self.responses, self.error = list(responses), error
        self.messages = SimpleNamespace(stream=self._stream)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @property
    def kwargs(self):
        return self.calls[-1]

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        final = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        events = [SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=final.text))]
        return _Ctx(events, final)


class _Ctx:
    def __init__(self, events, final):
        self.events, self.final = events, final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.final


def response(text='{"items": []}', stop="end_turn", category=None):
    usage = SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=800, cache_creation_input_tokens=0)
    return SimpleNamespace(stop_reason=stop, text=text, model="claude-test-final", usage=usage,
                           stop_details=SimpleNamespace(category=category) if category else None)


def claude(client, **llm):
    """ResearchChat mit Claude: Einstellungen von ZotLLM, Schlüssel im (Test-)Schlüsselspeicher, Attrappe als Client."""
    get_store().set("anthropic", "KEY")
    settings = Settings()
    settings.llm = settings.llm.model_copy(update={"helper_model": "claude-opus-5-5", **llm})

    def factory(provider, model, cfg, meter):
        chat = AnthropicChat(model, get_store().get(provider), meter=meter)
        chat.client = client
        return chat

    return ResearchChat(lambda: settings, get_store(), factory)


def test_claude_request_shape_and_usage():
    client = FakeAnthropic(response('{"items": [{"id": 1}]}'))
    chat = claude(client)
    assert chat and (chat.provider, chat.model, chat.effort, chat.vendor) == ("anthropic", "claude-opus-5-5", "low", "Anthropic")
    assert chat.label == "Anthropic Claude (claude-opus-5-5)" and chat.key_source == "ZotLLM (Schlüsselspeicher)"
    assert chat.complete_json("SYSTEM", "PROMPT", {"type": "object"}) == {"items": [{"id": 1}]}
    k = client.kwargs
    assert k["model"] == "claude-opus-5-5" and k["max_tokens"] == 16000
    assert k["betas"] == [FALLBACK_BETA] and k["fallbacks"] == "default"
    assert k["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert k["system"] == "SYSTEM" and k["cache_control"] == {"type": "ephemeral"}
    assert k["messages"] == [{"role": "user", "content": "PROMPT"}] and "thinking" not in k
    assert chat.usage == {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 800, "requests": 1}
    assert estimate_cost("claude-opus-5-5", chat.usage) == round((1200 * 4 + 300 * 20 + 800 * 0.2) / 1e6, 4)
    chat = claude(client, helper_model="claude-sonnet-5-5", helper_effort="medium")
    chat.complete_json("S", "P")
    assert client.kwargs["model"] == "claude-sonnet-5-5" and client.kwargs["output_config"] == {"effort": "medium"}


@pytest.mark.parametrize("resp, kind", [(response(stop="refusal", category="cyber"), "ai_refusal"),
                                        (response(stop="max_tokens"), "ai_truncated"),
                                        (response(text="kein JSON"), "ai_format")])
def test_claude_bad_responses(resp, kind):
    client = FakeAnthropic(resp)
    with pytest.raises(ResearchError) as e:
        claude(client).complete_json("S", "P")
    assert e.value.kind == kind
    if kind != "ai_refusal":  # abgeschnitten: einmal mit mehr Platz; kein JSON: einmal mit Korrekturhinweis
        assert len(client.calls) == 2


def _err(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("x", response=httpx2.Response(status, request=req), body=None)


@pytest.mark.parametrize("error, kind", [(_err(anthropic.AuthenticationError, 401), "ai_auth"),
                                         (_err(anthropic.NotFoundError, 404), "ai_model"),
                                         (_err(anthropic.RateLimitError, 429), "ai_rate"),
                                         (_err(anthropic.InternalServerError, 500), "ai_server")])
def test_claude_errors_are_explained(error, kind):
    with pytest.raises(ResearchError) as e:
        claude(FakeAnthropic(error=error)).complete_json("S", "P")
    assert e.value.kind == kind


def test_ai_endpoints(ai_service, zengine):
    from fastapi.testclient import TestClient

    from zotllm.server.app import create_app

    svc, _ = ai_service
    client = TestClient(create_app(zengine, research=svc))
    h = {"X-ZotLLM": "1"}
    assert client.get("/api/research/ai/status").json()["model"] == "claude-test"
    pid = pool(svc)
    assert counts(client.get(f"/api/research/projects/{pid}/ai/plan").json()["scopes"]["open"]) == {"new": 3, "failed": 0, "done": 0}
    r = client.post(f"/api/research/projects/{pid}/ai/screening", headers=h, json={"limit": 20}).json()
    assert r["processed"] == 3 and r["since"]
    items = client.get(f"/api/research/projects/{pid}/pool?status=ai_include").json()["items"]
    assert len(items) == 1 and items[0]["ai"]["reason"].startswith("Untersucht")
    r = client.post(f"/api/research/projects/{pid}/decisions/bulk", headers=h, json={
        "items": [{"record_id": items[0]["id"], "status": "include", "folder": 2}], "ai_shown": True}).json()
    assert r["count"] == 1
    assert client.post(f"/api/research/projects/{pid}/decisions/undo", headers=h).json()["undone"]["count"] == 1


def test_token_estimates_and_usage(store, sim, zotero):
    def responder(system, prompt, schema):
        chat.usage["input_tokens"] += 1000
        chat.usage["cache_read_input_tokens"] = chat.usage.get("cache_read_input_tokens", 0) + 200
        chat.usage["output_tokens"] += 150
        ids = ids_in(prompt)
        if "disciplines" in schema["properties"]:
            return {"disciplines": ["social"], "sources": [{"id": "openalex", "reason": "Basis."}], "note": ""}
        return {"items": [{"id": i, "label": "passend", "folder": 0, "criterion": "", "reason": "ok"} for i in ids]}

    chat = FakeChat(responder)
    chat.model = "claude-opus-5-5"
    svc = ResearchService(store, MemoryKeyStore(), {"web": zotero}, http=sim.http(), chat=chat)
    pid = pool(svc)
    plan = svc.ai_plan(pid)
    tok = plan["scopes"]["open"]["tokens"]
    assert tok["new"] > 50 and tok["failed"] == tok["done"] == 0 and plan["system_tokens"] > 100
    assert plan["out_per_record"] == 90 and tuple(plan["prices"]) == (4.0, 20.0, 0.2)

    r = svc.ai_screen(pid)
    assert (r["used"]["input"], r["used"]["output"], r["used"]["cached"], r["used"]["requests"]) == (1200, 150, 200, 1)
    assert r["used"]["cost"] == round((1000 * 4 + 150 * 20 + 200 * 0.2) / 1e6, 4)
    assert r["used_total"]["input"] == 1200

    for kind, out in (("sources", 450), ("blocks", 1500), ("folders", 350)):
        e = svc.ai_estimate(pid, kind, parent="test")
        assert e["input"] > 300 and e["output"] == out and e["cost"] is not None
    with pytest.raises(ResearchError):
        svc.ai_estimate(pid, "alles")
    assert svc.ai_sources(pid)["used"]["input"] == 1200

    md, _, _ = svc.protocol(pid, "md")
    assert "## KI-Nutzung" in md and "| Screening-Vorschläge | 1 | 1200 | 150 |" in md and "| **Summe** | 2 | 2400 | 300 |" in md


def test_ai_blocks_redo_single_block(store, sim, zotero):
    chat = FakeChat(lambda s, p, schema: {"blocks": [
        {"name": "Kontext", "kind": "include", "field": "tiab", "terms": ["online"], "mesh": [], "psycinfo": [], "reason": "x"},
        {"name": "phänomen", "kind": "include", "field": "tiab", "terms": ["teasing", "banter"], "mesh": [], "psycinfo": [], "reason": "neu"}],
        "note": ""})
    svc = ResearchService(store, MemoryKeyStore(), {"web": zotero}, http=sim.http(), chat=chat)
    pid = svc.create_project({"title": "x", "question": "Wie gehen Jugendliche mit Onlineaggressionen um?"})["id"]
    r = svc.ai_blocks(pid, [], focus={"name": "Phänomen", "kind": "include", "terms": ["cyberbull*"], "hint": "mehr Alltagsbegriffe"})
    assert [(b["name"], b["terms"]) for b in r["blocks"]] == [("Phänomen", ["teasing", "banter"])]
    prompt = chat.calls[-1][1]
    assert "Schlage nur den Block „Phänomen“ (Einschluss) neu vor" in prompt
    assert "nicht übernehmen wollten: cyberbull*" in prompt and "Wunsch der Forschenden: mehr Alltagsbegriffe" in prompt
