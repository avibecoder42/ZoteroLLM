"""Modul „Recherche“: Adapter von den schmalen Schnittstellen des Pakets ``zotivity.research`` (``research/ports.py``)
auf die Klassen von Zotivity.

Das Paket ``research`` kennt Zotivity nicht (es läuft unverändert auch in der eigenständigen Recherche-App). Hier
bekommt es:

- **ZoteroPort lokal:** ``ZoteroClientPort`` um Zotivitys ``ZoteroClient`` (lokale API von Zotero, Schreibfreigabe wie
  im übrigen Zotivity). Für die Web-API bringt das Paket ``ZoteroWebPort`` selbst mit.
- **KeyStore:** Zotivitys ``SecretStore`` (Namen ``zotero-web``, ``ncbi``, ``openalex``, ``semanticscholar``).
- **ChatModel:** ``ResearchChat`` um Zotivitys Sprachmodelle – dasselbe Modell wie für die Vorauswahl im
  Forschungsstand (Einstellungen: Hilfs- oder Hauptmodell), mit Token-Zähler und Kosten aus den Preisangaben.

Die Daten liegen in ``research.db`` im Datenordner von Zotivity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx

from zotivity import __version__, paths
from zotivity.catalog import PROVIDERS
from zotivity.i18n import tr
from zotivity.keystore import SecretStore, SecretStoreError, get_store
from zotivity.llm import ChatMessage, GenParams, LLMError, UsageMeter, make_chat_model, parse_json, retry_after_truncation, truncation
from zotivity.research import ai as research_ai
from zotivity.research.errors import ResearchError, SourceError, ZoteroWriteRefused
from zotivity.research.http import Http
from zotivity.research.ports import KEY_NCBI, KEY_OPENALEX, KEY_SEMANTICSCHOLAR, KEY_ZOTERO_WEB, MY_LIBRARY, is_fulltext
from zotivity.research.service import ResearchConfig, ResearchService
from zotivity.research.store import Store
from zotivity.research.zotero_web import ZoteroWebPort
from zotivity.zotero import ZoteroAuthRequired, ZoteroClient, ZoteroError

log = logging.getLogger(__name__)

try:  # die Anbieter-SDKs senden teils über httpx2
    import httpx2

    NETWORK_ERRORS: tuple = (OSError, httpx.TransportError, httpx2.TransportError)
except ImportError:  # pragma: no cover
    NETWORK_ERRORS = (OSError, httpx.TransportError)


def research_db_file():
    return paths.data_dir() / "research.db"


# Schlüssel der Datenbanken (Einstellungen → Datenbanken) und der Zotero-Web-API (Einstellungen → Zotero und Export)
RESEARCH_KEYS = {
    KEY_OPENALEX: {"label": "OpenAlex", "url": "https://openalex.org/settings/api", "hint": "Für OpenAlex nötig (kostenloses Konto)."},
    KEY_NCBI: {"label": "PubMed (NCBI)", "url": "https://www.ncbi.nlm.nih.gov/account/settings/",
               "hint": "Optional: 10 statt 3 Anfragen pro Sekunde an PubMed."},
    KEY_SEMANTICSCHOLAR: {"label": "Semantic Scholar", "url": "https://www.semanticscholar.org/product/api",
                          "hint": "Optional: ohne Schlüssel ist der Dienst oft überlastet."},
    KEY_ZOTERO_WEB: {"label": "Zotero-Web-API", "url": "https://www.zotero.org/settings/keys",
                     "hint": "Nur nötig, wenn eine Recherche über zotero.org statt über Zotero auf diesem Computer schreibt."},
}


# ------------------------------------------------------------------------------------------------ Zotero (lokal)
@contextmanager
def _zotero_errors():
    """Fehler des Zotero-Clients in die Fehlerarten der Recherche übersetzen (die Fachlogik fängt ResearchError)."""
    try:
        yield
    except ZoteroAuthRequired as e:
        raise ZoteroWriteRefused(tr(str(e)), "zotero_auth") from None
    except ZoteroError as e:
        raise SourceError(tr(str(e))) from None


class ZoteroClientPort:
    """ZoteroPort für Zotero auf diesem Computer. ``client`` liefert den aktuellen ZoteroClient (``engine.zotero``):
    Ändert sich die Adresse in den Einstellungen, legt Zotivity einen neuen an."""

    backend = "local"

    def __init__(self, client: Callable[[], ZoteroClient]):
        self._client = client

    def status(self) -> dict:
        out = {"ok": False, "backend": "local", "running": False, "write": False, "version": None, "message": ""}
        try:
            st = self._client().status()
        except Exception as e:  # noqa: BLE001 - status darf nicht werfen
            out["message"] = tr(str(e))
            return out
        out.update(running=st["running"], version=st.get("version"), ok=bool(st.get("local_api")))
        if not out["ok"]:
            out["message"] = tr(st.get("message") or "Zotero ist nicht erreichbar.")
            return out
        out["write"] = self.can_write()
        out["message"] = f"Zotero {out['version'] or ''} (lokal)" + ("" if out["write"] else " – Schreiben noch nicht freigegeben")
        return out

    def can_write(self, lib: str = MY_LIBRARY) -> bool:
        try:
            return self._client().has_write_access()
        except (ZoteroError, SecretStoreError):
            return False

    def authorize(self) -> bool:
        """Schreibrecht in Zotero anfragen (Dialog in Zotero; wie Einstellungen → Zotero)."""
        from zotivity.winfocus import start_dialog_watch

        stop = start_dialog_watch()  # Zotero öffnet den Dialog gern hinter anderen Fenstern
        try:
            with _zotero_errors():
                return self._client().authorize()
        finally:
            stop.set()

    def libraries(self) -> list[dict]:
        with _zotero_errors():
            groups = self._client().groups()
        named = sorted(((f"groups/{g['id']}", (g.get("data") or {}).get("name") or str(g["id"])) for g in groups),
                       key=lambda x: x[1].casefold())
        return [{"lib": MY_LIBRARY, "name": tr("Meine Bibliothek")}] + [{"lib": lib, "name": name} for lib, name in named]

    def collections(self, lib: str) -> list[dict]:
        with _zotero_errors():
            cols = self._client().collections(lib)
        return [{"key": c["key"], "name": c["data"]["name"], "parent": c["data"].get("parentCollection") or None}
                for c in cols]

    def iter_items(self, lib: str) -> Iterator[dict]:
        with _zotero_errors():
            for it in self._client().iter_items(lib, top=True, item_type="-attachment"):
                if (it.get("data") or {}).get("itemType") not in ("note", "attachment"):
                    yield it

    def create_collection(self, lib: str, name: str, parent: str | None = None) -> str:
        with _zotero_errors():
            return self._client().create_collection(lib, name, parent)

    def create_items(self, lib: str, items: list[dict]) -> list[dict]:
        with _zotero_errors():
            return self._client().create_items(lib, items)

    def add_to_collection(self, lib: str, collection_key: str, item_keys: list[str]) -> int:
        with _zotero_errors():
            return self._client().add_to_collection(lib, collection_key, item_keys)

    def has_fulltext(self, lib: str, item_key: str) -> bool:
        with _zotero_errors():
            return any(is_fulltext(c) for c in self._client().children(lib, item_key))

    def set_aside(self, lib: str, item_key: str, collection_keys: list[str], tag: str) -> None:
        with _zotero_errors():
            self._client().set_aside(lib, item_key, collection_keys, tag)


# ------------------------------------------------------------------------------------------------ Sprachmodell
VENDORS = {"anthropic": "Anthropic", "gemini": "Google", "openai": "OpenAI", "deepseek": "DeepSeek",
           "ollama": "Ollama (lokal)", "openai_compatible": "OpenAI-kompatibler Server"}
# Anbieter, die eine Antwort nach JSON-Schema einhalten können (llm/*_provider.py); sonst steht das Schema im Auftrag
SCHEMA_PROVIDERS = ("anthropic", "gemini", "openai")
KEY_SOURCES = {"keyring": "Zotivity (Schlüsselspeicher)", "env": "Umgebungsvariable"}
LLM_KINDS = {"auth": "ai_auth", "model": "ai_model", "rate_limit": "ai_rate", "connection": "ai_offline",
             "refusal": "ai_refusal", "context": "ai_request", "error": "ai_server"}
SCHEMA_HINT = ("\n\nAntworte ausschliesslich mit einem JSON-Objekt nach diesem JSON-Schema, ohne Erklärungen:\n"
               "```json\n{schema}\n```")


class ResearchChat:
    """ChatModel der Recherche über die Sprachmodelle von Zotivity.

    Welches Modell: wie die Vorauswahl im Forschungsstand (``review.screening_model``: Hilfsmodell, sonst
    Hauptmodell) mit dessen Denktiefe. Die Einstellungen werden bei jedem Aufruf gelesen – ein Wechsel unter
    Einstellungen → Sprachmodelle gilt sofort. Ohne Schlüssel ist das Objekt „falsch“: Die Recherche läuft dann
    ohne KI.
    """

    def __init__(self, settings: Callable, keys: SecretStore | None = None, factory: Callable = make_chat_model):
        self._settings = settings  # () -> Settings
        self._keys = keys or get_store()
        self._factory = factory
        self.meter = UsageMeter()
        self._model = None
        self._model_id: tuple | None = None
        self._no_schema: set[tuple[str, str]] = set()  # (Anbieter, Modell) hat das Schema abgelehnt

    # -- welches Modell -------------------------------------------------------------------------
    def _choice(self) -> tuple[str, str, str]:
        s = self._settings()
        llm = s.llm
        if s.review.screening_model == "main" or not llm.helper_model:
            return llm.provider, llm.model, llm.effort
        return llm.helper_provider or llm.provider, llm.helper_model, llm.helper_effort

    @property
    def provider(self) -> str:
        return self._choice()[0]

    @property
    def model(self) -> str:
        return self._choice()[1]

    @property
    def effort(self) -> str:
        return self._choice()[2]

    @property
    def vendor(self) -> str:
        return VENDORS.get(self.provider, self.provider)

    @property
    def label(self) -> str:
        provider, model, _ = self._choice()
        info = PROVIDERS.get(provider)
        return f"{info.label if info else provider} ({model})"

    @property
    def key_source(self) -> str:
        try:
            return KEY_SOURCES.get(self._keys.source(self.provider) or "", "")
        except SecretStoreError:
            return ""

    def __bool__(self) -> bool:
        provider, model, _ = self._choice()
        info = PROVIDERS.get(provider)
        if not model or info is None or not info.chat:
            return False
        try:
            return not info.needs_key or bool(self._keys.get(provider))
        except SecretStoreError:
            return False

    @property
    def usage(self) -> dict:
        """Verbrauch seit Dienststart in der Form der Recherche (Input ohne die Token aus dem Cache)."""
        u = self.meter.usage
        return {"input_tokens": max(0, u.input_tokens - u.cache_read_tokens), "output_tokens": u.output_tokens,
                "cache_read_input_tokens": u.cache_read_tokens, "requests": u.requests}

    def _chat_model(self):
        provider, model, _ = self._choice()
        try:
            key = self._keys.get(provider) or ""
        except SecretStoreError:
            key = ""
        llm = self._settings().llm
        ident = (provider, model, hashlib.sha256(key.encode()).hexdigest(), llm.base_urls.get(provider),
                 llm.request_timeout)
        if self._model is None or ident != self._model_id:
            self._model = self._factory(provider, model, llm, self.meter)
            self._model_id = ident
        return self._model

    # -- Aufruf ---------------------------------------------------------------------------------
    def complete_json(self, system: str, prompt: str, schema: dict | None = None) -> object:
        provider, model, effort = self._choice()
        native = bool(schema) and provider in SCHEMA_PROVIDERS and (provider, model) not in self._no_schema
        try:
            try:
                return self._ask(system, prompt, schema, native, effort)
            except LLMError as e:
                # Schema abgelehnt (z. B. älteres Modell): einmal ohne, das Schema steht dann im Auftrag
                if not native or e.kind != "error" or not any(w in str(e).lower() for w in ("schema", "format")):
                    raise
                log.info("%s:%s lehnt das JSON-Schema ab – Schema im Auftrag", provider, model)
                self._no_schema.add((provider, model))
                return self._ask(system, prompt, schema, False, effort)
        except LLMError as e:
            raise ResearchError(tr(str(e)), LLM_KINDS.get(e.kind, "ai_server")) from None
        except NETWORK_ERRORS:
            raise ResearchError(f"{self.vendor}: keine Verbindung (Netzwerk).", "ai_offline") from None

    def _ask(self, system: str, prompt: str, schema: dict | None, native: bool, effort: str) -> object:
        if schema and not native:
            prompt += SCHEMA_HINT.format(schema=json.dumps(schema, ensure_ascii=False))
        llm = self._settings().llm
        params = GenParams(max_tokens=llm.max_output_tokens, effort=effort, json_mode=True,
                           json_schema=schema if native else None)
        chat = self._chat_model()
        c = chat.complete(system, [ChatMessage("user", prompt)], params)
        kind = truncation(c.stop_reason)
        if kind:  # abgebrochen: einmal neu – mit mehr Platz bzw. kürzeren wörtlichen Zitaten
            params, prompt = retry_after_truncation(kind, params, prompt)
            c = chat.complete(system, [ChatMessage("user", prompt)], params)
            if truncation(c.stop_reason) == "length":
                raise ResearchError(f"{self.vendor}: Antwort abgeschnitten – kleinere Stapel versuchen.", "ai_truncated")
        try:
            return parse_json(c.text)
        except ValueError:
            pass
        retry = [ChatMessage("user", prompt), ChatMessage("assistant", c.text or "(leer)"),
                 ChatMessage("user", "Das war kein gültiges JSON. Antworte ausschliesslich mit dem JSON-Objekt, ohne Erklärungen.")]
        try:
            return parse_json(chat.complete(system, retry, params).text)
        except ValueError:
            raise ResearchError(f"{self.vendor}: Antwort war kein gültiges JSON.", "ai_format") from None


def sync_prices(llm) -> None:
    """Preise aus Einstellungen → Sprachmodelle für die Kostenrichtwerte der Recherche (USD je 1 Mio. Token, wie
    in Zotivity ohne Rabatt für Token aus dem Cache). Andere Währungen bleiben aussen vor – die Recherche zeigt USD."""
    if (llm.price_currency or "USD").upper() != "USD":
        return
    for model, price in (llm.prices or {}).items():
        if isinstance(price, (list, tuple)) and len(price) == 2 and all(isinstance(p, (int, float)) for p in price):
            research_ai.PRICES[model] = (float(price[0]), float(price[1]), float(price[0]))


# ------------------------------------------------------------------------------------------------ Aufbau
def build_research_service(engine, db_path=None) -> ResearchService:
    """Recherche-Dienst für den Server: research.db im Datenordner, Schlüssel aus dem Schlüsselspeicher, Zotero
    lokal über Zotivitys Client oder über die Web-API, KI mit dem eingestellten Modell."""
    keys = get_store()
    http = Http(user_agent=f"Zotivity/{__version__} (Recherche)")
    sync_prices(engine.settings.llm)
    engine.settings_store.on_change(lambda old, new: sync_prices(new.llm))
    ports = {"web": ZoteroWebPort(http, keys), "local": ZoteroClientPort(lambda: engine.zotero())}
    service = ResearchService(Store(db_path or research_db_file()), keys, ports, http=http,
                              chat=ResearchChat(lambda: engine.settings, keys), config=ResearchConfig(default_backend="local"))
    prefer_local_zotero(service, keys)
    return service


def prefer_local_zotero(service: ResearchService, keys) -> int:
    """Zotivity spricht mit Zotero auf diesem Computer. Ältere Recherchen standen auf der Web-API (Erbe der eigenständigen
    App) und scheiterten ohne deren Schlüssel, obwohl Zotero lief: Diese stellen wir um."""
    try:
        if keys.get(KEY_ZOTERO_WEB):
            return 0
    except SecretStoreError:
        return 0
    moved = [p["id"] for p in service.store.projects() if p["zotero_backend"] == "web"]
    for pid in moved:
        service.store.update_project(pid, {"zotero_backend": "local"})
    return len(moved)
