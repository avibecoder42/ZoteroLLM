"""Tests des Moduls „Recherche“ (zotllm.research und die Adapter in research_adapters.py) – ohne Netz, Zotero nur als
Attrappe, nie der echte Schlüsselspeicher."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from research_fakes import FakeZoteroPort, MemoryKeyStore, SourceSim  # noqa: E402

from zotllm.research.service import ResearchConfig, ResearchService  # noqa: E402
from zotllm.research.store import Store  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Echte Verbindungen sind in Tests verboten – alles läuft über MockTransport."""

    def refuse(self, request):
        raise AssertionError(f"Netzwerkzugriff im Test: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    try:  # die Anbieter-SDKs senden teils über httpx2
        import httpx2

        monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse)
    except ImportError:  # pragma: no cover
        pass


KEY_ENV = ("ANTHROPIC_API_KEY", "ZOTLLM_ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ZOTLLM_GEMINI_API_KEY",
           "OPENAI_API_KEY", "ZOTLLM_OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ZOTLLM_DEEPSEEK_API_KEY")


@pytest.fixture(autouse=True)
def no_real_keys(memory_keyring, monkeypatch):
    """Tests lesen nie den echten Schlüsselspeicher (nur den Speicher im Arbeitsspeicher aus tests/conftest.py) und
    keine Schlüssel aus der Umgebung."""
    for var in KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    return memory_keyring


@pytest.fixture
def sim():
    return SourceSim()


@pytest.fixture
def zotero():
    return FakeZoteroPort()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "research.db")
    yield s
    s.close()


@pytest.fixture
def service(store, sim, zotero):
    return ResearchService(store, MemoryKeyStore(), {"web": zotero, "local": zotero}, http=sim.http(),
                           config=ResearchConfig(email="test@example.org", user_name="Test"), sleep=lambda s: None)
