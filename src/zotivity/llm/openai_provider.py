"""OpenAI (ChatGPT) sowie OpenAI-kompatible Schnittstellen: DeepSeek, Ollama, LM Studio …"""

from __future__ import annotations

import base64
from collections.abc import Iterator

import openai

from zotivity.llm.base import ChatMessage, ChatModel, GenParams, LLMError, StreamEvent, Usage

_LABELS = {"openai": "OpenAI", "deepseek": "DeepSeek", "ollama": "Ollama", "openai_compatible": "Server"}


class OpenAIChat(ChatModel):
    def __init__(
        self,
        model: str,
        api_key: str | None,
        provider: str = "openai",
        base_url: str | None = None,
        timeout: float = 600.0,
        meter=None,
    ):
        super().__init__(model, meter)
        self.provider = provider
        self.name = _LABELS.get(provider, provider)
        if provider in ("openai", "deepseek") and not api_key:
            raise LLMError(f"Kein {self.name}-API-Schlüssel gespeichert.", "auth")
        kwargs = {"api_key": api_key or "not-needed", "timeout": timeout, "max_retries": 3}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)
        # Parameter, die das Modell nachweislich ablehnt, werden nicht erneut gesendet
        self._dropped: set[str] = set()
        self._token_key = "max_completion_tokens" if provider == "openai" else "max_tokens"

    def _messages(self, system: str, messages: list[ChatMessage]) -> list[dict]:
        out: list[dict] = []
        if system:
            role = "developer" if self.provider == "openai" else "system"
            out.append({"role": role, "content": system})
        for m in messages:
            if m.images:
                parts: list[dict] = [
                    {"type": "image_url",
                     "image_url": {"url": "data:image/png;base64," + base64.b64encode(img).decode("ascii")}}
                    for img in m.images
                ]
                parts.append({"type": "text", "text": m.content})
                out.append({"role": m.role, "content": parts})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def _kwargs(self, system: str, messages: list[ChatMessage], params: GenParams) -> dict:
        kw: dict = {
            "model": self.model,
            "messages": self._messages(system, messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        kw[self._token_key] = params.max_tokens
        if params.temperature is not None:
            kw["temperature"] = params.temperature
        if params.effort:
            effort = params.effort
            if self.provider == "openai" and effort == "max":
                effort = "xhigh"
            kw["reasoning_effort"] = effort
        if params.json_mode and params.json_schema and self.provider == "openai":
            kw["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "answer", "schema": params.json_schema, "strict": False}}
        elif params.json_mode:
            kw["response_format"] = {"type": "json_object"}
        for k in self._dropped:
            kw.pop(k, None)
        return kw

    def _stream(self, system: str, messages: list[ChatMessage], params: GenParams) -> Iterator[StreamEvent]:
        for attempt in range(4):
            kw = self._kwargs(system, messages, params)
            try:
                stream = self.client.chat.completions.create(**kw)
                break
            except openai.BadRequestError as e:
                msg = str(e).lower()
                dropped = False
                for param in ("temperature", "reasoning_effort", "response_format", "stream_options"):
                    if param in kw and param in msg and param not in self._dropped:
                        self._dropped.add(param)
                        dropped = True
                if not dropped and self._token_key in msg:
                    self._token_key = "max_tokens" if self._token_key == "max_completion_tokens" else "max_completion_tokens"
                    dropped = True
                if not dropped or attempt == 3:
                    raise self._error(e) from e
            except openai.APIError as e:
                raise self._error(e) from e

        usage = Usage(requests=1)
        stop, model = "", self.model
        try:
            for chunk in stream:
                if getattr(chunk, "model", None):
                    model = chunk.model
                if chunk.usage:
                    usage.input_tokens = chunk.usage.prompt_tokens or 0
                    usage.output_tokens = chunk.usage.completion_tokens or 0
                    details = getattr(chunk.usage, "prompt_tokens_details", None)
                    usage.cache_read_tokens = (getattr(details, "cached_tokens", 0) or 0) if details else 0
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.delta and choice.delta.content:
                    yield StreamEvent("text", text=choice.delta.content)
                if choice.finish_reason:
                    stop = choice.finish_reason
        except openai.APIError as e:
            raise self._error(e) from e
        if stop == "content_filter":
            raise LLMError(f"{self.name}: Antwort durch Inhaltsfilter blockiert.", "refusal")
        yield StreamEvent("done", usage=usage, stop_reason=stop, model=model)

    def _error(self, e: Exception) -> LLMError:
        n = self.name
        if isinstance(e, openai.AuthenticationError):
            return LLMError(f"{n}: API-Schlüssel ungültig.", "auth")
        if isinstance(e, openai.NotFoundError):
            return LLMError(f"{n}: Modell „{self.model}“ nicht gefunden.", "model")
        if isinstance(e, openai.RateLimitError):
            return LLMError(f"{n}: Ratenlimit oder Guthaben erschöpft – {e}", "rate_limit")
        if isinstance(e, openai.APIConnectionError):
            return LLMError(f"{n}: keine Verbindung ({self.client.base_url}).", "connection")
        if isinstance(e, openai.BadRequestError):
            kind = "context" if "context" in str(e).lower() else "error"
            return LLMError(f"{n}: ungültige Anfrage – {e}", kind)
        return LLMError(f"{n}-Fehler: {e}", "error")

    def list_models(self) -> list[str]:
        try:
            ids = [m.id for m in self.client.models.list()]
        except openai.APIError:
            return []
        if self.provider == "openai":
            skip = ("embedding", "whisper", "tts", "dall-e", "image", "audio", "realtime", "moderation",
                    "transcribe", "search", "sora", "davinci", "babbage")
            ids = [i for i in ids if not any(s in i for s in skip)]
        return sorted(ids)
