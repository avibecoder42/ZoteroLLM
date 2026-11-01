"""Einstellungen (JSON, ohne Geheimnisse – API-Schlüssel liegen im Schlüsselspeicher)."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from zotivity import paths

Effort = Literal["", "low", "medium", "high", "xhigh", "max"]

# Word (.docx) und OpenDocument-Text (.odt) – lesbar ab Version 0.9.0 (Einstellungen der Version 2)
OFFICE_TYPES = ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.oasis.opendocument.text"]


class ZoteroSettings(BaseModel):
    api_url: str = "http://127.0.0.1:23119"
    # "users/0" = eigene Bibliothek, "groups/<id>" = Gruppenbibliothek
    libraries: list[str] = Field(default_factory=lambda: ["users/0"])


class IndexingSettings(BaseModel):
    # manual: nur auf Anforderung; background: automatisch, solange Zotero offen ist
    mode: Literal["manual", "background"] = "manual"
    interval_minutes: int = Field(10, ge=1, le=1440)
    content_types: list[str] = Field(
        default_factory=lambda: ["application/pdf", "application/epub+zip", "text/html", *OFFICE_TYPES]
    )
    # Seiten mit weniger Zeichen gelten als Scan ohne Textebene
    min_chars_per_page: int = Field(40, ge=0)
    max_pages_per_document: int = Field(3000, ge=1)
    # Falls Zotero bereits einen Volltext hat (z. B. HTML-Schnappschüsse), diesen nutzen
    use_zotero_fulltext_fallback: bool = True
    # Texterkennung für Scans (benötigt eine Tesseract-Installation)
    ocr: bool = False
    ocr_languages: str = "deu+eng"
    # Pause zwischen Dokumenten (Sekunden), damit der Rechner bedienbar bleibt
    throttle_seconds: float = Field(0.0, ge=0, le=10)
    # Texte in einem eigenen Prozess lesen: eine defekte Datei kann dann nur diesen Prozess abstürzen lassen
    isolate_extraction: bool = True
    extract_timeout_seconds: int = Field(300, ge=10, le=7200)
    # Ruhezustand des Rechners verhindern, solange indexiert wird
    keep_awake: bool = True
    # Hintergrundmodus in Etappen: nur in diesem Zeitfenster (Stunden 0–23, z. B. 22 → 7) und höchstens
    # so viele Texte pro Lauf (0 = unbegrenzt)
    background_from_hour: int | None = Field(None, ge=0, le=23)
    background_to_hour: int | None = Field(None, ge=0, le=23)
    background_max_docs: int = Field(0, ge=0, le=100000)
    # Nach einem Lauf eine Sicherung des Index anlegen (höchstens alle 12 Stunden, die zwei neuesten bleiben)
    backup_after_run: bool = True
    # Dubletten (dasselbe Werk mehrfach in Zotero): vor einem Lauf von Hand fragen, welche Kopie verwendet wird;
    # sonst (und bei Gleichstand) gilt die Regel mit dieser bevorzugten Bibliothek
    ask_duplicates: bool = True
    duplicate_library: str = "users/0"


class ChunkingSettings(BaseModel):
    chunk_tokens: int = Field(400, ge=64, le=4000)
    overlap_tokens: int = Field(60, ge=0, le=1000)
    min_chunk_tokens: int = Field(30, ge=0, le=500)
    # Titel/Autor/Jahr vor jeden Abschnitt setzen (nur für das Embedding)
    metadata_header: bool = True
    # Abstract als eigener Abschnitt indexieren (wichtig für Dokumentsuche)
    index_abstracts: bool = True


class EmbeddingSettings(BaseModel):
    # "builtin": eingebaute Laufzeit (llama.cpp) mit Modellen aus dem Katalog (embeddings/model_catalog.py)
    provider: str = "builtin"
    model: str = "bge-m3"
    # Matryoshka-Verkürzung (OpenAI text-embedding-3, Gemini, eingebaute Modelle); None = Modellstandard
    dimensions: int | None = None
    batch_size: int = Field(16, ge=1, le=512)
    # None = automatisch je nach Modell (Katalog bzw. catalog.EMBEDDING_PRESETS)
    query_prefix: str | None = None
    document_prefix: str | None = None
    base_url: str | None = None
    request_timeout: float = Field(120.0, ge=5)
    # Ollama und eingebaute Laufzeit: CPU-Threads (None = physische Kerne)
    num_thread: int | None = Field(None, ge=1, le=256)
    # Nur Ollama: Geräteauswahl
    device: Literal["auto", "cpu", "gpu"] = "auto"
    # Eingebaute Laufzeit: gleichzeitig verarbeitete Abschnitte und Minuten bis zum Entladen des Modells
    parallel: int = Field(4, ge=1, le=16)
    keep_alive_minutes: int = Field(10, ge=1, le=240)
    # Fällt der Embedding-Dienst aus (z. B. Ollama neu gestartet), so lange warten statt abzubrechen
    outage_wait_minutes: int = Field(10, ge=0, le=240)


class LLMSettings(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-opus-5-5"
    # Günstigeres Hilfsmodell für Suchanfragen, Vorauswahl, Auswertungsblätter
    helper_provider: str = "anthropic"
    helper_model: str = "claude-haiku-5-5"
    # None = Standard des Modells (manche Modelle akzeptieren keine Temperatur)
    temperature: float | None = Field(None, ge=0, le=2)
    max_output_tokens: int = Field(16000, ge=256, le=128000)
    # Denk-/Reasoning-Tiefe (Claude: effort, OpenAI/DeepSeek: reasoning_effort, Gemini: thinking_level)
    effort: Effort = ""
    helper_effort: Effort = "low"
    base_urls: dict[str, str] = Field(default_factory=dict)
    request_timeout: float = Field(600.0, ge=10)
    # Selbst gepflegte Preise je Modell: [Eingabe, Ausgabe] pro 1 Mio. Tokens (für Kostenschätzungen)
    prices: dict[str, list[float]] = Field(default_factory=dict)
    price_currency: str = "USD"


class RetrievalSettings(BaseModel):
    # Anzahl Textstellen, die an das LLM gehen
    top_k: int = Field(15, ge=1, le=200)
    # Kandidaten je Suchverfahren vor der Fusion
    candidate_k: int = Field(80, ge=5, le=2000)
    # Anteil Bedeutungssuche (1.0) vs. Stichwortsuche (0.0) in der Fusion
    hybrid_weight: float = Field(0.6, ge=0, le=1)
    rrf_k: int = Field(60, ge=1, le=1000)
    # MMR: 1.0 = nur Relevanz, kleiner = mehr Vielfalt
    mmr_lambda: float = Field(0.75, ge=0, le=1)
    max_chunks_per_doc: int = Field(3, ge=1, le=50)
    min_similarity: float = Field(0.0, ge=-1, le=1)
    # Nachbarabschnitte mitschicken (0 = aus)
    neighbor_chunks: int = Field(0, ge=0, le=3)
    # Mehrfachsuche: das Hilfsmodell formuliert mehrere Suchanfragen (DE/EN, Synonyme)
    multi_query: bool = True
    n_queries: int = Field(4, ge=1, le=20)
    # Zusätzliche Recherche-Runden: das Modell prüft die Treffer und sucht gezielt nach
    research_rounds: int = Field(0, ge=0, le=5)
    rerank: Literal["none", "llm", "cross_encoder"] = "none"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidates: int = Field(40, ge=5, le=300)
    context_token_budget: int = Field(16000, ge=1000, le=900000)


class ReviewSettings(BaseModel):
    n_queries: int = Field(14, ge=3, le=60)
    candidate_docs: int = Field(100, ge=10, le=1000)
    per_query_k: int = Field(150, ge=10, le=2000)
    # Bis zu dieser Länge wird der ganze Text gelesen, sonst die relevanten Teile
    fulltext_token_limit: int = Field(60000, ge=2000, le=900000)
    relevant_chunks_if_long: int = Field(40, ge=5, le=500)
    # Auswertungsblätter mit "helper" (günstig) oder "main"
    sheet_model: Literal["helper", "main"] = "main"
    screening_model: Literal["helper", "main"] = "helper"
    target_words: int = Field(4000, ge=300, le=40000)
    write_notes_to_zotero: bool = True
    note_tag: str = "Zotivity-Auswertung"
    create_collection: bool = True
    parallel_requests: int = Field(3, ge=1, le=16)
    # Belege im Forschungsstand öffnen in Zotero den Eintrag oder die PDF an der zitierten Seite
    link_target: Literal["pdf", "item"] = "pdf"


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(23120, ge=1024, le=65535)
    # Dienst beenden, wenn Zotero so lange geschlossen ist (0 = nie)
    exit_after_zotero_closed_minutes: int = Field(0, ge=0)


class Settings(BaseModel):
    version: int = 2
    # Sprache der Oberfläche (Wörterbücher in static/js/i18n) und der KI-Ausgaben („auto“ = Sprache der Frage)
    language: str = Field("de", pattern=r"^[a-z]{2}$")
    output_language: str = Field("auto", pattern=r"^(auto|[a-z]{2})$")
    appearance: Literal["system", "light", "gray", "dark"] = "system"
    # Zitierstil für Exporte (Word/LaTeX/Text): ID eines in Zotero installierten Stils (zotero/styles.py)
    citation_style: str = "http://www.zotero.org/styles/apa"
    # Kennzeichnung für Belege aus Quellen ohne Seitenzahlen (je nach Stil Seitenangabe oder Suffix im Zotero-Beleg)
    citation_no_page: str = Field("o. S.", max_length=40)
    # Update-Manifest (HTTPS oder Datei-/Netzwerkpfad), leer = keine Update-Prüfung
    update_url: str = ""
    check_updates_on_start: bool = True
    # Zentraler Katalog der Embedding-Modelle (HTTPS oder Datei), leer = nur der mitgelieferte Katalog
    model_catalog_url: str = ""
    # Presets für Such- und Antwortwerte: eingebaute (siehe presets.py) und eigene
    active_preset: str = "ausgewogen"
    presets: dict[str, dict] = Field(default_factory=dict)
    zotero: ZoteroSettings = Field(default_factory=ZoteroSettings)
    indexing: IndexingSettings = Field(default_factory=IndexingSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    review: ReviewSettings = Field(default_factory=ReviewSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("base_urls", "prices", "presets"):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Gespeicherte Einstellungen älterer Versionen ergänzen (die Datei enthält alle Werte, auch Standardwerte)."""
    if int(raw.get("version") or 1) < 2:
        types = (raw.get("indexing") or {}).get("content_types")
        if isinstance(types, list):  # Word und OpenDocument lesen (neu in 0.9.0)
            raw["indexing"]["content_types"] = types + [t for t in OFFICE_TYPES if t not in types]
        raw["version"] = 2
    return raw


class SettingsStore:
    """Thread-sichere Verwaltung der Einstellungen mit atomarem Speichern."""

    def __init__(self, path=None):
        self.path = path or paths.settings_file()
        self._lock = threading.RLock()
        self._listeners: list = []
        self._settings = self._load()

    def _load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return Settings.model_validate(_deep_merge(Settings().model_dump(), _migrate(raw)))
        except (ValueError, ValidationError):
            backup = self.path.with_suffix(".invalid.json")
            os.replace(self.path, backup)
            return Settings()

    def get(self) -> Settings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update(self, patch: dict[str, Any]) -> Settings:
        """Teil-Aktualisierung; wirft ValidationError bei ungültigen Werten."""
        with self._lock:
            merged = _deep_merge(self._settings.model_dump(), patch)
            new = Settings.model_validate(merged)
            old = self._settings
            self._settings = new
            self._save(new)
        for cb in list(self._listeners):
            cb(old, new)
        return new.model_copy(deep=True)

    def replace(self, settings: Settings) -> None:
        self.update(settings.model_dump())

    def on_change(self, callback) -> None:
        self._listeners.append(callback)

    def _save(self, settings: Settings) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
