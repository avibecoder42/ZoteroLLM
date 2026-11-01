import pytest
from pydantic import ValidationError

from zotivity.keystore import SecretStore, SecretStoreError
from zotivity.settings import SettingsStore


def test_keys_roundtrip_and_masking(memory_keyring):
    store = SecretStore()
    store.set("openai", "sk-test-1234567890abcd")
    assert store.get("openai") == "sk-test-1234567890abcd"
    assert store.masked("openai") == "••••abcd"
    assert store.source("openai") == "keyring"
    assert store.delete("openai") is True
    assert store.get("openai") is None
    assert store.delete("openai") is False


def test_empty_key_rejected():
    with pytest.raises(SecretStoreError):
        SecretStore().set("openai", "   ")


def test_env_fallback(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key-xyz-0000")
    store = SecretStore()
    assert store.get("deepseek") == "env-key-xyz-0000"
    assert store.source("deepseek") == "env"


def test_insecure_backend_refused(monkeypatch):
    store = SecretStore()
    monkeypatch.setattr(store, "backend_info", lambda: {"backend": "keyrings.alt.file.PlaintextKeyring", "secure": False})
    with pytest.raises(SecretStoreError):
        store.set("openai", "sk-abc")


def test_settings_partial_update_and_validation(tmp_path):
    ss = SettingsStore(tmp_path / "s.json")
    s = ss.update({"retrieval": {"top_k": 7}, "llm": {"provider": "gemini", "model": "gemini-3.5-flash"}})
    assert s.retrieval.top_k == 7 and s.retrieval.candidate_k == 80
    assert SettingsStore(tmp_path / "s.json").get().llm.provider == "gemini"
    with pytest.raises(ValidationError):
        ss.update({"retrieval": {"hybrid_weight": 3}})
    assert ss.get().retrieval.hybrid_weight == 0.6
    # Keine Schlüssel in der Einstellungsdatei
    assert "sk-" not in (tmp_path / "s.json").read_text(encoding="utf-8")


def test_settings_change_listener(tmp_path):
    ss = SettingsStore(tmp_path / "s.json")
    seen = []
    ss.on_change(lambda old, new: seen.append((old.embedding.model, new.embedding.model)))
    ss.update({"embedding": {"model": "embeddinggemma"}})
    assert seen == [("bge-m3", "embeddinggemma")]
