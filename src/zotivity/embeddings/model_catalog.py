"""Katalog der Embedding-Modelle für die eingebaute Laufzeit (llama.cpp, GGUF).

Drei Quellen werden zusammengeführt:

1. der mitgelieferte Katalog ``zotivity/data/embedding_catalog.json`` – kommt mit jeder Programmversion;
2. ein zentraler Katalog (Einstellung ``model_catalog_url``, später die Datei im GitHub-Repository) –
   er gilt nur, wenn er neuer ist, und wird lokal zwischengespeichert: Ohne Internet gilt der zuletzt
   geladene, sonst der mitgelieferte;
3. eigene Modelle, über die Namenssuche hinzugefügt – diese Liste wird nie überschrieben.

Ein Katalog beschreibt nur Modelle (Quelle, Prüfsumme, Präfixe, Messwerte) und enthält keinen ausführbaren
Code; jede Datei wird vor der Übernahme gegen das Schema geprüft.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from zotivity import paths

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BUNDLED = DATA_DIR / "embedding_catalog.json"
SCHEMA = 1
USER_GROUP = "user"
_lock = threading.RLock()
_cache: dict[str, object] = {}


class CatalogError(ValueError):
    pass


Loc = dict[str, str]


class ModelFile(BaseModel):
    name: str = Field(pattern=r"^[^/\\:*?\"<>|]+\.gguf$", max_length=200)
    quant: str = Field("", max_length=40)
    bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Source(BaseModel):
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$", max_length=200)
    revision: str = Field("main", pattern=r"^[\w.-]+$", max_length=80)
    official: bool = False


class Runtime(BaseModel):
    pooling: Literal["", "none", "mean", "cls", "last"] = ""
    query_prefix: str = Field("", max_length=1000)
    document_prefix: str = Field("", max_length=1000)
    # Tokens je Abschnitt, die das Modell auf einmal verarbeitet (längere Texte werden gekürzt)
    ctx: int = Field(2048, ge=128, le=32768)


class Reference(BaseModel):
    """Messwerte auf dem Referenzrechner des Katalogs (Kurztest)."""

    tok_per_s: float | None = Field(None, gt=0)
    ram_mb: int | None = Field(None, ge=0)
    top1: int | None = Field(None, ge=0)


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,100}$")
    name: str = Field(min_length=1, max_length=200)
    vendor: str = Field("", max_length=200)
    year: int | None = Field(None, ge=2000, le=2100)
    group: str = Field("alternatives", max_length=40)
    default: bool = False
    params_m: float | None = Field(None, gt=0)
    # Rechenaufwand je Token in Millionen Parametern (ohne Wortschatz-Tabelle) – für Zeitschätzungen
    compute_m: float | None = Field(None, gt=0)
    dim: int | None = Field(None, ge=8, le=16384)
    matryoshka: list[int] = Field(default_factory=list)
    context: int | None = Field(None, ge=1)
    languages: Loc = Field(default_factory=dict)
    license: str = Field("", max_length=100)
    mteb: float | None = Field(None, ge=0, le=100)
    mteb_note: Loc = Field(default_factory=dict)
    strengths: Loc = Field(default_factory=dict)
    disciplines: Loc = Field(default_factory=dict)
    notes: Loc = Field(default_factory=dict)
    model_url: str = Field("", max_length=500)
    source: Source
    file: ModelFile
    runtime: Runtime = Field(default_factory=Runtime)
    aliases: list[str] = Field(default_factory=list)
    reference: Reference = Field(default_factory=Reference)
    # Selbst hinzugefügt (Namenssuche): nicht geprüft
    user: bool = False
    # Herkunft: "bundled", "remote" oder "user" (beim Laden gesetzt)
    origin: str = "bundled"

    @field_validator("model_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("model_url muss mit https:// beginnen")
        return v

    @property
    def download_url(self) -> str:
        return f"https://huggingface.co/{self.source.repo}/resolve/{self.source.revision}/{self.file.name}"

    def text(self, field: str, lang: str) -> str:
        loc = getattr(self, field) or {}
        return loc.get(lang) or loc.get("en") or loc.get("de") or ""


class Group(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    label: Loc


class Catalog(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_version: int = Field(alias="schema", ge=1)
    version: str = Field(pattern=r"^\d{4}\.\d{1,2}\.\d{1,2}(\.\d+)?$")
    about: str = ""
    reference: dict = Field(default_factory=dict)
    groups: list[Group] = Field(default_factory=list)
    models: list[ModelEntry]

    @model_validator(mode="after")
    def _unique(self):
        ids = [m.id for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("Modell-IDs im Katalog sind nicht eindeutig")
        return self


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def parse(raw: bytes | str, origin: str) -> Catalog:
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise CatalogError(f"Katalog ist kein gültiges JSON: {e}") from e
    if not isinstance(data, dict):
        raise CatalogError("Katalog hat ein unerwartetes Format.")
    if int(data.get("schema") or 0) > SCHEMA:
        raise CatalogError("Der Modellkatalog verlangt eine neuere Version von Zotivity.")
    try:
        cat = Catalog.model_validate(data)
    except ValidationError as e:
        raise CatalogError(f"Katalog ungültig: {e.errors()[0].get('loc')} – {e.errors()[0].get('msg')}") from e
    for m in cat.models:
        m.origin = origin
        m.user = False
    return cat


def cache_file() -> Path:
    return paths.data_dir() / "embedding_catalog.json"


def user_file() -> Path:
    return paths.models_dir() / "user_models.json"


def bundled() -> Catalog:
    with _lock:
        if "bundled" not in _cache:
            _cache["bundled"] = parse(BUNDLED.read_bytes(), "bundled")
        return _cache["bundled"]  # type: ignore[return-value]


def _cached_remote() -> Catalog | None:
    path = cache_file()
    if not path.exists():
        return None
    try:
        return parse(path.read_bytes(), "remote")
    except (OSError, CatalogError):
        return None


def current() -> Catalog:
    """Der neuere von mitgeliefertem und zuletzt geladenem zentralen Katalog."""
    with _lock:
        if "current" not in _cache:
            cat = bundled()
            remote = _cached_remote()
            if remote and version_key(remote.version) > version_key(cat.version):
                cat = remote
            _cache["current"] = cat
        return _cache["current"]  # type: ignore[return-value]


def invalidate() -> None:
    with _lock:
        _cache.pop("current", None)
        _cache.pop("user", None)
        _cache.pop("overrides", None)


def refresh(url: str) -> dict:
    """Zentralen Katalog laden; übernommen wird er nur, wenn er neuer ist als der aktuelle."""
    from zotivity.updates import UpdateError, read_source

    url = (url or "").strip()
    if not url:
        return {"configured": False, "updated": False, "version": current().version}
    try:
        raw = read_source(url, 2 * 1024 * 1024)
    except UpdateError:
        raise
    except OSError as e:
        raise CatalogError(f"Modellkatalog nicht erreichbar: {e}") from e
    cat = parse(raw, "remote")
    before = current()
    updated = version_key(cat.version) > version_key(before.version)
    if updated:
        tmp = cache_file().with_suffix(".tmp")
        tmp.write_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
        os.replace(tmp, cache_file())
        invalidate()
    return {"configured": True, "updated": updated, "version": current().version, "remote_version": cat.version}


# -- Eigene Modelle --------------------------------------------------------------------------------
def user_models() -> list[ModelEntry]:
    with _lock:
        if "user" not in _cache:
            out: list[ModelEntry] = []
            path = user_file()
            if path.exists():
                try:
                    for raw in json.loads(path.read_text(encoding="utf-8")).get("models", []):
                        try:
                            m = ModelEntry.model_validate(raw)
                        except ValidationError:
                            continue
                        m.user, m.origin, m.group = True, "user", USER_GROUP
                        out.append(m)
                except (OSError, ValueError):
                    pass
            _cache["user"] = out
        return list(_cache["user"])  # type: ignore[arg-type]


def _write_user(models: list[ModelEntry]) -> None:
    path = user_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"models": [m.model_dump(exclude={"origin"}) for m in models]}, indent=1,
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    invalidate()


def save_user_model(entry: ModelEntry) -> ModelEntry:
    if any(m.id == entry.id for m in current().models):
        raise CatalogError("Dieses Modell steht bereits im Katalog.")
    entry = entry.model_copy(update={"user": True, "origin": "user", "group": USER_GROUP})
    with _lock:
        models = [m for m in user_models() if m.id != entry.id] + [entry]
        _write_user(models)
    return entry


def update_user_model(model_id: str, **changes) -> ModelEntry:
    with _lock:
        models = user_models()
        for i, m in enumerate(models):
            if m.id == model_id:
                data = m.model_dump()
                for k, v in changes.items():
                    if k == "runtime":
                        data["runtime"] = {**data["runtime"], **v}
                    else:
                        data[k] = v
                models[i] = ModelEntry.model_validate(data)
                _write_user(models)
                return models[i]
    raise CatalogError("Eigenes Modell nicht gefunden.")


def remove_user_model(model_id: str) -> bool:
    with _lock:
        models = user_models()
        rest = [m for m in models if m.id != model_id]
        if len(rest) == len(models):
            return False
        _write_user(rest)
        return True


# -- Eigene Präfixe für Katalogmodelle ----------------------------------------------------------------
PREFIX_KEYS = ("query_prefix", "document_prefix")


def overrides_file() -> Path:
    return paths.models_dir() / "prefix_overrides.json"


def prefix_overrides() -> dict[str, dict[str, str]]:
    """Vom Benutzer geänderte Präfixe je Katalogmodell (eigene Modelle speichern sie in ihrem Eintrag)."""
    with _lock:
        if "overrides" not in _cache:
            out: dict[str, dict[str, str]] = {}
            path = overrides_file()
            if path.exists():
                try:
                    for mid, v in (json.loads(path.read_text(encoding="utf-8")) or {}).items():
                        if isinstance(v, dict):
                            out[str(mid)] = {k: str(v[k])[:1000] for k in PREFIX_KEYS if isinstance(v.get(k), str)}
                except (OSError, ValueError):
                    pass
            _cache["overrides"] = out
        return dict(_cache["overrides"])  # type: ignore[arg-type]


def set_prefix_override(model_id: str, prefixes: dict[str, str] | None) -> None:
    """Präfixe eines Katalogmodells ändern; None oder die Katalogwerte stellen den Standard wieder her."""
    entry = next((m for m in current().models if m.id == model_id), None)
    if entry is None:
        raise CatalogError("Modell nicht im Katalog")
    with _lock:
        data = prefix_overrides()
        changed = {k: v for k, v in (prefixes or {}).items() if k in PREFIX_KEYS and v != getattr(entry.runtime, k)}
        if changed:
            data[model_id] = changed
        else:
            data.pop(model_id, None)
        path = overrides_file()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        _cache.pop("overrides", None)


def _with_overrides(m: ModelEntry, overrides: dict[str, dict[str, str]]) -> ModelEntry:
    o = overrides.get(m.id)
    return m.model_copy(update={"runtime": m.runtime.model_copy(update=o)}) if o else m


def catalog_runtime(model_id: str) -> Runtime | None:
    """Laufzeitwerte eines Katalogmodells ohne eigene Präfixe (für „Standard wiederherstellen“)."""
    entry = next((m for m in current().models if m.id == model_id), None)
    return entry.runtime if entry else None


# -- Abfragen --------------------------------------------------------------------------------------
def all_models() -> list[ModelEntry]:
    overrides = prefix_overrides()
    return [_with_overrides(m, overrides) for m in current().models] + user_models()


def get(model_id: str) -> ModelEntry | None:
    return next((m for m in all_models() if m.id == model_id), None)


def default_model() -> ModelEntry:
    models = current().models
    return next((m for m in models if m.default), models[0])


def groups(lang: str) -> list[dict]:
    out = [{"id": g.id, "label": g.label.get(lang) or g.label.get("en") or g.id} for g in current().groups]
    out.append({"id": USER_GROUP, "label": "Eigene Modelle" if lang == "de" else "Your models"})
    return out


def match_alias(name: str) -> ModelEntry | None:
    """Katalogmodell zu einem Namen aus einem anderen Anbieter (z. B. Ollama „bge-m3:latest“)."""
    want = name.lower().removesuffix(":latest")
    for m in current().models:
        if want == m.id or want in (a.lower().removesuffix(":latest") for a in m.aliases):
            return m
    return None
