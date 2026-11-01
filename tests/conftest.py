import hashlib
import re
import sys
from pathlib import Path

import keyring
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakes import FakeZotero, MemoryKeyring  # noqa: E402

from zotivity import keystore  # noqa: E402
from zotivity.embeddings.base import Embedder  # noqa: E402
from zotivity.engine import Engine  # noqa: E402
from zotivity.index.store import Store  # noqa: E402
from zotivity.settings import EmbeddingSettings, SettingsStore  # noqa: E402
from zotivity.zotero import ZoteroClient  # noqa: E402


class HashEmbedder(Embedder):
    """Deterministischer Test-Embedder (Wort-Hashing, 256 Dimensionen) – kein Modell nötig."""

    provider = "test"

    def __init__(self):
        super().__init__(EmbeddingSettings(provider="test", model="hash"))
        self._dim = 256

    def _embed(self, texts, is_query):
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"\w+", t.lower()):
                h = int(hashlib.md5(w[:6].encode()).hexdigest(), 16)
                out[i, h % 256] += 1.0
        return out


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    """Nie den echten Schlüsselspeicher des Rechners anfassen."""
    backend = MemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    monkeypatch.setattr(keystore, "_store", None)
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def no_real_zotero_styles(monkeypatch):
    """Nie die Zotero-Einstellungen und Stile des Rechners lesen (Tests mit Stilen setzen einen eigenen Ordner)."""
    from zotivity.zotero import styles

    monkeypatch.setattr(styles, "zotero_data_dir", lambda store=None: None)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOTIVITY_HOME", str(tmp_path))
    ss = SettingsStore(tmp_path / "settings.json")
    # Schnell und ohne Nebenwirkungen: Lesen im selben Prozess, kein Wachhalten, keine Sicherungen
    # (die Robustheitsfunktionen haben eigene Tests in test_robustness.py)
    ss.update({"indexing": {"isolate_extraction": False, "keep_awake": False, "backup_after_run": False}})
    eng = Engine(ss, Store(tmp_path / "index.sqlite3"))
    emb = HashEmbedder()
    monkeypatch.setattr(eng, "embedder", lambda: emb)
    yield eng
    eng.store.close()


@pytest.fixture
def fake_zotero(tmp_path):
    return FakeZotero(tmp_path / "storage")


@pytest.fixture
def zengine(engine, fake_zotero, monkeypatch):
    """Engine, deren Zotero-Client mit der simulierten lokalen API spricht."""
    client = ZoteroClient("http://127.0.0.1:23119", keystore=keystore.get_store(), transport=fake_zotero.transport())
    monkeypatch.setattr(engine, "zotero", lambda: client)
    # Was indexiert wird, bestimmen die Wissenskorpora: hier die ganze eigene Bibliothek
    engine.store.create_corpus("Alles", ["users/0:*"])
    return engine
