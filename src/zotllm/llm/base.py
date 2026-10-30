"""Gemeinsame Schnittstelle für alle LLM-Anbieter."""

from __future__ import annotations

import json
import re
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field, replace


class LLMError(RuntimeError):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind  # auth, model, rate_limit, context, refusal, connection, error


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str
    images: list[bytes] = field(default_factory=list)  # PNG-Daten (z. B. PDF-Seiten mit Grafiken)


@dataclass
class GenParams:
    max_tokens: int = 4096
    temperature: float | None = None
    effort: str = ""  # low | medium | high | xhigh | max | "" (Modellstandard)
    json_mode: bool = False
    # JSON-Schema für die Antwort (nur mit json_mode): Anbieter, die es können, halten es strikt ein; die übrigen
    # ignorieren es – wer es braucht, beschreibt es dann im Auftrag (so die Recherche, research_adapters.py)
    json_schema: dict | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    requests: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.requests += other.requests

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "requests": self.requests,
        }


@dataclass
class StreamEvent:
    type: str  # "text" | "done"
    text: str = ""
    usage: Usage | None = None
    stop_reason: str = ""
    model: str = ""


@dataclass
class Completion:
    text: str
    usage: Usage
    stop_reason: str = ""
    model: str = ""


def truncation(stop_reason: str) -> str:
    """Hat das Modell vorzeitig aufgehört? "length": Ausgabelimit erreicht (bei Gemini zählen Denk-Token mit);
    "recitation": der Anbieter hat abgebrochen, weil die Ausgabe eine längere Passage wörtlich wiedergab (Gemini);
    "" sonst. Die Anbieter melden das unterschiedlich (Gross-/Kleinschreibung, eigene Namen)."""
    s = (stop_reason or "").lower()
    if s in ("length", "max_tokens", "model_context_window_exceeded"):
        return "length"
    if s == "recitation":
        return "recitation"
    return ""


# Zusatz für einen zweiten Versuch, wenn der Anbieter wegen wörtlicher Wiedergabe abgebrochen hat
RECITATION_HINT = ("Wichtig: Ein erster Versuch brach ab, weil die Ausgabe eine längere Passage wörtlich wiedergab. "
                   "Wörtliche Zitate höchstens ein Satz, besser ein kurzer Teilsatz; alles Übrige in eigenen Worten.")


def retry_after_truncation(kind: str, params: GenParams, prompt: str, max_tokens_cap: int = 16000) -> tuple[GenParams, str]:
    """Parameter und Auftrag für einen zweiten Versuch: mehr Platz bzw. kürzere wörtliche Zitate."""
    if kind == "length":
        return replace(params, max_tokens=min(max_tokens_cap, max(params.max_tokens * 2, 8000))), prompt
    return params, f"{prompt}\n\n{RECITATION_HINT}"


class UsageMeter:
    """Thread-sicherer Zähler für Token-Verbrauch (pro Auftrag)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.usage = Usage()

    def add(self, u: Usage | None) -> None:
        if u:
            with self._lock:
                self.usage.add(u)


class ChatModel(ABC):
    provider: str = ""

    def __init__(self, model: str, meter: UsageMeter | None = None):
        self.model = model
        self.meter = meter

    @abstractmethod
    def _stream(self, system: str, messages: list[ChatMessage], params: GenParams) -> Iterator[StreamEvent]:
        ...

    def list_models(self) -> list[str]:
        return []

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def stream(self, system: str, messages: list[ChatMessage], params: GenParams) -> Iterator[StreamEvent]:
        for ev in self._stream(system, messages, params):
            if ev.type == "done" and self.meter:
                self.meter.add(ev.usage)
            yield ev

    def complete(self, system: str, messages: list[ChatMessage], params: GenParams) -> Completion:
        parts: list[str] = []
        usage, stop, model = Usage(), "", self.model
        for ev in self.stream(system, messages, params):
            if ev.type == "text":
                parts.append(ev.text)
            elif ev.type == "done":
                usage = ev.usage or usage
                stop = ev.stop_reason
                model = ev.model or model
        return Completion(text="".join(parts), usage=usage, stop_reason=stop, model=model)

    def complete_json(self, system: str, prompt: str, params: GenParams | None = None) -> object:
        """Antwort als JSON; ein zweiter Versuch mit Korrekturhinweis bei ungültigem JSON."""
        params = params or GenParams()
        params = GenParams(params.max_tokens, params.temperature, params.effort, json_mode=True)
        messages = [ChatMessage("user", prompt)]
        c = self.complete(system, messages, params)
        kind = truncation(c.stop_reason)
        if kind:  # abgebrochen (unvollständiges JSON): einmal neu – mit mehr Platz bzw. kürzeren wörtlichen Zitaten
            params, prompt = retry_after_truncation(kind, params, prompt)
            messages = [ChatMessage("user", prompt)]
            c = self.complete(system, messages, params)
        text = c.text
        try:
            return parse_json(text)
        except ValueError:
            messages += [
                ChatMessage("assistant", text or "(leer)"),
                ChatMessage("user", "Das war kein gültiges JSON. Antworte ausschliesslich mit dem JSON-Objekt, ohne Erklärungen."),
            ]
            return parse_json(self.complete(system, messages, params).text)

    def test(self) -> dict:
        c = self.complete("", [ChatMessage("user", "Antworte nur mit: OK")], GenParams(max_tokens=2000))
        return {"ok": True, "reply": c.text.strip()[:100], "model": c.model or self.model}


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> object:
    text = (text or "").strip()
    text = _FENCE.sub("", text).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    # erstes vollständiges JSON-Objekt/-Array heraussuchen
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except ValueError:
                continue
    raise ValueError("Antwort enthält kein gültiges JSON")
