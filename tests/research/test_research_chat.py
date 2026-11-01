"""KI der Recherche über die Sprachmodelle von Zotivity (ResearchChat in research_adapters.py) – ohne Netz und ohne den
echten Schlüsselspeicher. Gemini mit einer Attrappe des google-genai-Clients, sonst eine Modell-Attrappe."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import keyring
import pytest
from google.genai import errors as genai_errors
from google.genai import types
from research_fakes import FakeZoteroPort

from zotivity.keystore import get_store
from zotivity.llm import ChatModel, LLMError, StreamEvent, Usage
from zotivity.llm.gemini_provider import GeminiChat
from zotivity.research import ai as research_ai
from zotivity.research.errors import ResearchError
from zotivity.research.service import ResearchService
from zotivity.research_adapters import SCHEMA_HINT, ResearchChat, ZoteroClientPort, build_research_service, sync_prices
from zotivity.settings import Settings

SCHEMA = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"], "additionalProperties": False}


def settings_with(**llm) -> Settings:
    s = Settings()
    s.llm = s.llm.model_copy(update=llm)
    return s


# ------------------------------------------------------------------------------------------- Gemini über Zotivity
class FakeGenai:
    """Wie ``genai.Client`` für Zotivitys GeminiChat: ``models.generate_content_stream(**kw)``; Antworten oder Fehler der
    Reihe nach (die letzte Antwort wiederholt sich)."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.models = SimpleNamespace(generate_content_stream=self._stream)

    def _stream(self, **kw):
        self.calls.append(kw)
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, Exception):
            raise out
        return iter([out])


def reply(text='{"items": []}', finish=types.FinishReason.STOP):
    parts = [SimpleNamespace(text="überlege …", thought=True), SimpleNamespace(text=text, thought=None)]
    usage = SimpleNamespace(prompt_token_count=1200, candidates_token_count=300, thoughts_token_count=50,
                            cached_content_token_count=800)
    return SimpleNamespace(candidates=[SimpleNamespace(finish_reason=finish, content=SimpleNamespace(parts=parts))],
                           usage_metadata=usage, model_version="gemini-3.8-flash")


def api_error(cls, code, message):
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


def gemini(client, model="gemini-flash-latest", effort="low"):
    get_store().set("gemini", "G-KEY")
    settings = settings_with(helper_provider="gemini", helper_model=model, helper_effort=effort)

    def factory(provider, model, cfg, meter):
        chat = GeminiChat(model, get_store().get(provider), meter=meter)
        chat.client = client
        return chat

    return ResearchChat(lambda: settings, get_store(), factory)


def test_gemini_request_shape_and_usage():
    client = FakeGenai(reply('{"items": [{"id": 1}]}'))
    chat = gemini(client)
    assert chat.complete_json("SYSTEM", "PROMPT", SCHEMA) == {"items": [{"id": 1}]}
    kw = client.calls[0]
    assert kw["model"] == "gemini-flash-latest" and kw["contents"][0].parts[0].text == "PROMPT"
    cfg = kw["config"]
    assert cfg.system_instruction == "SYSTEM" and cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == SCHEMA and cfg.max_output_tokens == 16000
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert chat.usage == {"input_tokens": 400, "output_tokens": 350, "cache_read_input_tokens": 800, "requests": 1}
    assert (chat.provider, chat.vendor, chat.label) == ("gemini", "Google", "Google Gemini (gemini-flash-latest)")
    assert chat.key_source == "Zotivity (Schlüsselspeicher)"


def test_gemini_retries_without_thinking_or_schema():
    client = FakeGenai(api_error(genai_errors.ClientError, 400, "thinking_level is not supported for this model"),
                       api_error(genai_errors.ClientError, 400, "Invalid JSON schema: enum"),
                       reply('```json\n{"items": []}\n```'))
    chat = gemini(client, model="gemini-pro-latest")
    assert chat.complete_json("S", "P", SCHEMA) == {"items": []}
    assert client.calls[1]["config"].thinking_config is None
    assert client.calls[2]["config"].response_json_schema is None and client.calls[2]["model"] == "gemini-pro-latest"


@pytest.mark.parametrize("resp, kind", [(reply(finish=types.FinishReason.SAFETY), "ai_refusal"),
                                        (reply(finish=types.FinishReason.PROHIBITED_CONTENT), "ai_refusal"),
                                        (reply(finish=types.FinishReason.MAX_TOKENS), "ai_truncated"),
                                        (reply(text="kein JSON"), "ai_format")])
def test_gemini_bad_responses(resp, kind):
    with pytest.raises(ResearchError) as e:
        gemini(FakeGenai(resp)).complete_json("S", "P")
    assert e.value.kind == kind


@pytest.mark.parametrize("error, kind", [(api_error(genai_errors.ClientError, 400, "API key not valid."), "ai_auth"),
                                         (api_error(genai_errors.ClientError, 403, "denied"), "ai_auth"),
                                         (api_error(genai_errors.ClientError, 404, "not found"), "ai_model"),
                                         (api_error(genai_errors.ClientError, 429, "quota"), "ai_rate"),
                                         (api_error(genai_errors.ServerError, 503, "overloaded"), "ai_server"),
                                         (ConnectionError("weg"), "ai_offline")])
def test_gemini_errors_are_explained(error, kind):
    with pytest.raises(ResearchError) as e:
        gemini(FakeGenai(error)).complete_json("S", "P")
    assert e.value.kind == kind


# ------------------------------------------------------------------------------------------- Modell-Attrappe
class Scripted(ChatModel):
    """Antwortet der Reihe nach mit (Text, Stoppgrund) oder wirft LLMError; merkt sich Parameter und Auftrag."""

    def __init__(self, model, *outcomes, provider="deepseek", meter=None):
        super().__init__(model, meter)
        self.provider = provider
        self.outcomes = list(outcomes)
        self.seen = []

    def _stream(self, system, messages, params):
        self.seen.append((params, messages[-1].content))
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, Exception):
            raise out
        text, stop = out
        yield StreamEvent("text", text=text)
        yield StreamEvent("done", usage=Usage(input_tokens=100, output_tokens=20, requests=1), stop_reason=stop)


def scripted(settings, model):
    built = []

    def factory(provider, name, cfg, meter):
        model.meter = meter
        built.append((provider, name))
        return model

    chat = ResearchChat(lambda: settings, get_store(), factory)
    return chat, built


def test_schema_in_prompt_without_native_support():
    get_store().set("deepseek", "D")
    model = Scripted("deepseek-v4-flash", ('{"items": []}', "stop"))
    chat, built = scripted(settings_with(helper_provider="deepseek", helper_model="deepseek-v4-flash"), model)
    assert chat.complete_json("S", "PROMPT", SCHEMA) == {"items": []}
    params, prompt = model.seen[0]
    assert params.json_mode and params.json_schema is None and params.effort == "low"
    assert prompt.startswith("PROMPT") and '"additionalProperties": false' in prompt and SCHEMA_HINT.split("{")[0] in prompt
    assert built == [("deepseek", "deepseek-v4-flash")] and chat.vendor == "DeepSeek"


def test_rejected_schema_falls_back_to_prompt():
    get_store().set("openai", "O")
    model = Scripted("gpt-5.6-sol", LLMError("OpenAI: ungültige Anfrage – Invalid schema for response_format", "error"),
                     ('{"items": [1]}', "stop"), provider="openai")
    chat, _ = scripted(settings_with(helper_provider="openai", helper_model="gpt-5.6-sol"), model)
    assert chat.complete_json("S", "P", SCHEMA) == {"items": [1]}
    assert model.seen[0][0].json_schema == SCHEMA and model.seen[1][0].json_schema is None
    assert '"required": ["items"]' in model.seen[1][1]
    chat.complete_json("S", "P", SCHEMA)  # merkt sich das Modell: gleich ohne Schema
    assert model.seen[2][0].json_schema is None
    assert chat.usage["requests"] == 2  # die abgelehnte Anfrage liefert keinen Verbrauch


def test_invalid_json_is_asked_again_once():
    get_store().set("deepseek", "D")
    model = Scripted("m", ("Hier ist es: kaputt", "stop"), ('{"ok": true}', "stop"))
    chat, _ = scripted(settings_with(helper_provider="deepseek", helper_model="m"), model)
    assert chat.complete_json("S", "P") == {"ok": True}
    assert "kein gültiges JSON" in model.seen[1][1]


# ------------------------------------------------------------------------------------------- Schlüssel, Modellwahl
def test_keys_come_from_zotivity_store(store, sim, monkeypatch):
    keys = get_store()
    keys.set("openalex", "OA-KEY")
    keyring.set_password("ZoteroLLM", "ncbi", "N-ALT")  # früherer Name wird übernommen
    svc = ResearchService(store, keys, {"web": FakeZoteroPort()}, http=sim.http(), sleep=lambda s: None)
    assert svc.info()["keys"] == {"ncbi": True, "openalex": True, "semanticscholar": False, "zotero-web": False}
    assert svc.openalex().api_key == "OA-KEY" and keys.get("ncbi") == "N-ALT"
    assert keyring.get_password("Zotivity", "ncbi") == "N-ALT"

    chat = ResearchChat(lambda: settings_with(helper_provider="gemini", helper_model="gemini-flash-latest"), keys)
    assert not chat and chat.key_source == ""
    monkeypatch.setenv("GEMINI_API_KEY", "G-ENV")
    assert chat and chat.key_source == "Umgebungsvariable"


def test_store_errors_mean_no_key(monkeypatch):
    def broken(service, name):
        raise keyring.errors.KeyringLocked("gesperrt")

    monkeypatch.setattr(keyring, "get_password", broken)
    chat = ResearchChat(lambda: Settings(), get_store())
    assert not chat and chat.key_source == ""


def test_chat_follows_settings(store, sim):
    s = Settings()  # Anthropic: Haupt- claude-opus-5-5, Hilfsmodell claude-haiku-5-5 (Aufwand low)
    chat = ResearchChat(lambda: s, get_store())
    svc = ResearchService(store, get_store(), {}, http=sim.http(), chat=chat)
    assert not chat and svc.ai_status()["available"] is False  # ohne Schlüssel: Recherche ohne KI
    with pytest.raises(ResearchError) as e:
        svc.ai_sources(svc.create_project({"title": "x", "question": "Frage?"})["id"])
    assert e.value.kind == "ai_missing"

    get_store().set("anthropic", "A")
    st = svc.ai_status()
    assert st["available"] and (st["model"], st["effort"], st["provider"]) == ("claude-haiku-5-5", "low", "anthropic")
    s.review = s.review.model_copy(update={"screening_model": "main"})  # wie die Vorauswahl im Forschungsstand
    s.llm = s.llm.model_copy(update={"effort": "high"})
    assert (chat.model, chat.effort) == ("claude-opus-5-5", "high")
    assert tuple(svc.ai_status()["prices"]) == (4.0, 20.0, 0.2)

    s.llm = s.llm.model_copy(update={"provider": "ollama", "model": "gemma4:e4b"})
    assert chat and chat.vendor == "Ollama (lokal)" and chat.key_source == ""  # lokal: kein Schlüssel nötig


def test_chat_model_is_rebuilt_when_key_or_model_changes():
    get_store().set("deepseek", "D1")
    s = settings_with(helper_provider="deepseek", helper_model="m1")
    model = Scripted("m", ('{"a": 1}', "stop"))
    chat, built = scripted(s, model)
    chat.complete_json("S", "P")
    chat.complete_json("S", "P")
    assert built == [("deepseek", "m1")]
    get_store().set("deepseek", "D2")
    chat.complete_json("S", "P")
    s.llm = s.llm.model_copy(update={"helper_model": "m2"})
    chat.complete_json("S", "P")
    assert built == [("deepseek", "m1"), ("deepseek", "m1"), ("deepseek", "m2")]


# ------------------------------------------------------------------------------------------- Preise, Aufbau
def test_prices_from_zotivity_settings(monkeypatch):
    monkeypatch.setattr(research_ai, "PRICES", dict(research_ai.PRICES))
    sync_prices(settings_with(prices={"gemini-flash-latest": [0.5, 3.0], "kaputt": [1]}).llm)
    assert research_ai.PRICES["gemini-flash-latest"] == (0.5, 3.0, 0.5) and "kaputt" not in research_ai.PRICES
    assert research_ai.estimate_cost("gemini-flash-latest", {"input_tokens": 1_000_000, "output_tokens": 0}) == 0.5
    sync_prices(settings_with(prices={"claude-opus-5-5": [9.0, 9.0]}, price_currency="CHF").llm)
    assert research_ai.PRICES["claude-opus-5-5"] == (4.0, 20.0, 0.2)  # die Recherche rechnet in USD


def test_build_research_service(zengine, monkeypatch):
    monkeypatch.setattr(research_ai, "PRICES", dict(research_ai.PRICES))
    svc = build_research_service(zengine)
    try:
        db = Path(svc.store.path)
        assert db.name == "research.db" and db.parent == zengine.store.path.parent  # Datenordner von Zotivity
        assert set(svc.zotero) == {"web", "local"} and isinstance(svc.zotero["local"], ZoteroClientPort)
        assert svc.zotero["local"].status()["ok"]  # Zotivitys Client gegen die simulierte lokale API
        assert isinstance(svc.chat, ResearchChat) and svc.http.client.headers["User-Agent"].startswith("Zotivity/")
        zengine.settings_store.update({"llm": {"prices": {"claude-haiku-5-5": [1.0, 5.0]}}})
        assert research_ai.PRICES["claude-haiku-5-5"] == (1.0, 5.0, 1.0)  # Änderung in den Einstellungen gilt sofort
    finally:
        svc.store.close()
