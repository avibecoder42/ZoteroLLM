"""Statischer Katalog der unterstützten Anbieter.

Die Modelllisten sind nur Vorschläge für die Oberfläche. Mit gültigem Schlüssel
lädt die App die tatsächlich verfügbaren Modelle beim Anbieter (``list_models``),
weil sich die Modellnamen häufig ändern.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    needs_key: bool
    key_url: str = ""
    chat: bool = True
    embeddings: bool = False
    default_base_url: str = ""
    chat_models: tuple[str, ...] = ()
    embedding_models: tuple[str, ...] = ()
    notes: str = ""
    # Empfohlene Modelle beim Wechsel auf diesen Anbieter (Haupt- bzw. Hilfsmodell)
    default_main: str = ""
    default_helper: str = ""
    # Teilstrings von Modellnamen, die für Textantworten ungeeignet sind (Bild, Audio, …)
    hide_models: tuple[str, ...] = ()


PROVIDERS: dict[str, ProviderInfo] = {
    p.id: p
    for p in [
        ProviderInfo(
            id="builtin",
            label="Eingebaut (lokal)",
            needs_key=False,
            chat=False,
            embeddings=True,
            notes="Läuft in Zotivity selbst (llama.cpp), ohne zusätzliche Installation; keine Daten verlassen den "
                  "Computer. Weitere Modelle über „Modell hinzufügen …“.",
        ),
        ProviderInfo(
            id="anthropic",
            label="Anthropic Claude",
            needs_key=True,
            key_url="https://platform.claude.com/settings/keys",
            chat_models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"),
            default_main="claude-opus-5-5",
            default_helper="claude-haiku-5-5",
            notes="Keine eigenen Embeddings – dafür lokal (Ollama) oder OpenAI/Gemini wählen.",
        ),
        ProviderInfo(
            id="openai",
            label="OpenAI (ChatGPT)",
            needs_key=True,
            key_url="https://platform.openai.com/api-keys",
            embeddings=True,
            chat_models=("gpt-6-astra", "gpt-5.6-sol"),
            default_main="gpt-6-astra",
            default_helper="gpt-5.6-sol",
            embedding_models=("text-embedding-3-large", "text-embedding-3-small"),
        ),
        ProviderInfo(
            id="gemini",
            label="Google Gemini",
            needs_key=True,
            key_url="https://aistudio.google.com/apikey",
            embeddings=True,
            # "-latest"-Aliase zeigen automatisch auf das jeweils aktuelle Modell (geprüft 10.10.2026:
            # pro → gemini-3.1-pro-preview, flash → gemini-3.8-flash)
            chat_models=("gemini-pro-latest", "gemini-flash-latest", "gemini-flash-lite-latest"),
            default_main="gemini-pro-latest",
            default_helper="gemini-flash-latest",
            hide_models=("tts", "image", "lyria", "robotics", "nano-banana", "transcribe", "computer-use",
                         "antigravity", "deep-research", "embedding", "imagen", "veo", "omni", "aqa"),
            embedding_models=("gemini-embedding-2", "gemini-embedding-001"),
        ),
        ProviderInfo(
            id="deepseek",
            label="DeepSeek",
            needs_key=True,
            key_url="https://platform.deepseek.com/api_keys",
            default_base_url="https://api.deepseek.com",
            chat_models=("deepseek-v4-pro", "deepseek-v4-flash"),
            default_main="deepseek-v4-pro",
            default_helper="deepseek-v4-flash",
            notes="Keine Embeddings beim Anbieter.",
        ),
        ProviderInfo(
            id="ollama",
            label="Ollama (lokal)",
            needs_key=False,
            embeddings=True,
            default_base_url="http://127.0.0.1:11434",
            chat_models=("gemma4:e4b", "qwen3:4b"),
            default_main="gemma4:e4b",
            default_helper="qwen3:4b",
            embedding_models=(
                "bge-m3",
                "embeddinggemma-2:270m",
                "embeddinggemma",
                "snowflake-arctic-embed2",
                "qwen3-embedding",
                "nomic-embed-text",
            ),
            notes="Läuft vollständig auf diesem Rechner, keine Daten verlassen den Computer.",
        ),
        ProviderInfo(
            id="openai_compatible",
            label="OpenAI-kompatibler Server",
            needs_key=False,
            embeddings=True,
            default_base_url="http://127.0.0.1:1234/v1",
            notes="Z. B. LM Studio, vLLM, OpenRouter. Schlüssel optional.",
        ),
        ProviderInfo(
            id="sentence_transformers",
            label="Sentence-Transformers (lokal, Hugging Face)",
            needs_key=False,
            chat=False,
            embeddings=True,
            embedding_models=("google/embeddinggemma-2", "BAAI/bge-m3"),
            notes="Optional: pip install \"zotivity[local]\". Für Modelle, die (noch) nicht in Ollama verfügbar sind.",
        ),
    ]
}


def chat_providers() -> list[ProviderInfo]:
    return [p for p in PROVIDERS.values() if p.chat]


def sort_chat_models(provider: str, models: list[str]) -> list[str]:
    """Für die Auswahlliste: ungeeignete Modelle ausblenden, Empfehlungen zuerst, dann neueste zuerst."""
    info = PROVIDERS.get(provider)
    hide = info.hide_models if info else ()
    models = [m for m in dict.fromkeys(models) if not any(h in m for h in hide)]
    preferred = [m for m in (info.chat_models if info else ()) if m in models]
    rest = sorted((m for m in models if m not in preferred), reverse=True)
    return preferred + rest


def embedding_providers() -> list[ProviderInfo]:
    return [p for p in PROVIDERS.values() if p.embeddings]


@dataclass(frozen=True)
class EmbeddingPreset:
    """Modellspezifische Präfixe. Viele Embedding-Modelle wurden mit
    Aufgaben-Präfixen trainiert und suchen ohne sie spürbar schlechter."""

    query_prefix: str = ""
    document_prefix: str = ""
    max_input_chars: int = 8000
    notes: str = ""
    extra: dict = field(default_factory=dict)


EMBEDDING_PRESETS: dict[str, EmbeddingPreset] = {
    "bge-m3": EmbeddingPreset(max_input_chars=16000),
    # EmbeddingGemma 2 (Okt. 2026): dieselben Aufgaben-Präfixe wie Version 1, Kontext 8192 Tokens;
    # bei Ollama „embeddinggemma-2:270m“ (nur Text) bzw. :570m; Matryoshka 768/512/256/128
    "embeddinggemma-2": EmbeddingPreset(
        query_prefix="task: search result | query: ",
        document_prefix="title: none | text: ",
        max_input_chars=24000,
    ),
    "embeddinggemma": EmbeddingPreset(
        query_prefix="task: search result | query: ",
        document_prefix="title: none | text: ",
        max_input_chars=6000,
    ),
    "snowflake-arctic-embed2": EmbeddingPreset(query_prefix="query: ", max_input_chars=16000),
    "nomic-embed-text": EmbeddingPreset(query_prefix="search_query: ", document_prefix="search_document: "),
    "qwen3-embedding": EmbeddingPreset(
        query_prefix="Instruct: Given a research question, retrieve relevant passages from scholarly literature\nQuery: ",
        max_input_chars=24000,
    ),
    "mxbai-embed-large": EmbeddingPreset(
        query_prefix="Represent this sentence for searching relevant passages: ", max_input_chars=2000
    ),
}


def embedding_preset(model: str) -> EmbeddingPreset:
    name = model.lower().split("/")[-1].split(":")[0]
    # Längster passender Name gewinnt („embeddinggemma-2“ vor „embeddinggemma“)
    for key in sorted(EMBEDDING_PRESETS, key=len, reverse=True):
        if name.startswith(key):
            return EMBEDDING_PRESETS[key]
    return EmbeddingPreset()
