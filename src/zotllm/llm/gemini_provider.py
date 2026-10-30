"""Google Gemini über das google-genai-SDK."""

from __future__ import annotations

from collections.abc import Iterator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from zotllm.llm.base import ChatMessage, ChatModel, GenParams, LLMError, StreamEvent, Usage

_THINKING = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


class GeminiChat(ChatModel):
    provider = "gemini"

    def __init__(self, model: str, api_key: str, timeout: float = 600.0, meter=None):
        super().__init__(model, meter)
        if not api_key:
            raise LLMError("Kein Gemini-API-Schlüssel gespeichert.", "auth")
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))
        self._no_thinking_level = False
        self._no_temperature = False
        self._no_schema = False

    def _contents(self, messages: list[ChatMessage]) -> list[types.Content]:
        out = []
        for m in messages:
            parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in m.images]
            parts.append(types.Part.from_text(text=m.content))
            out.append(types.Content(role="model" if m.role == "assistant" else "user", parts=parts))
        return out

    def _config(self, system: str, params: GenParams) -> types.GenerateContentConfig:
        kw: dict = {"max_output_tokens": params.max_tokens}
        if system:
            kw["system_instruction"] = system
        if params.temperature is not None and not self._no_temperature:
            kw["temperature"] = params.temperature
        if params.effort and not self._no_thinking_level:
            kw["thinking_config"] = types.ThinkingConfig(thinking_level=_THINKING.get(params.effort, "high"))
        if params.json_mode:
            kw["response_mime_type"] = "application/json"
            if params.json_schema and not self._no_schema:
                kw["response_json_schema"] = params.json_schema
        return types.GenerateContentConfig(**kw)

    def _stream(self, system: str, messages: list[ChatMessage], params: GenParams) -> Iterator[StreamEvent]:
        contents = self._contents(messages)
        usage = Usage(requests=1)
        stop, model = "", self.model
        for attempt in range(3):
            try:
                emitted = False
                for chunk in self.client.models.generate_content_stream(
                    model=self.model, contents=contents, config=self._config(system, params)
                ):
                    if chunk.usage_metadata:
                        um = chunk.usage_metadata
                        usage.input_tokens = um.prompt_token_count or 0
                        usage.output_tokens = (um.candidates_token_count or 0) + (um.thoughts_token_count or 0)
                        usage.cache_read_tokens = um.cached_content_token_count or 0
                    if getattr(chunk, "model_version", None):
                        model = chunk.model_version
                    if chunk.candidates:
                        cand = chunk.candidates[0]
                        if cand.finish_reason:
                            stop = str(cand.finish_reason.value if hasattr(cand.finish_reason, "value")
                                       else cand.finish_reason)
                        for part in (cand.content.parts if cand.content and cand.content.parts else []):
                            if part.text and not part.thought:
                                emitted = True
                                yield StreamEvent("text", text=part.text)
                break
            except genai_errors.ClientError as e:
                msg = str(e).lower()
                if not emitted and attempt < 2 and "thinking" in msg and not self._no_thinking_level:
                    self._no_thinking_level = True
                    continue
                if not emitted and attempt < 2 and "temperature" in msg and not self._no_temperature:
                    self._no_temperature = True
                    continue
                if not emitted and attempt < 2 and "schema" in msg and params.json_schema and not self._no_schema:
                    self._no_schema = True  # Modell ohne Schema-Unterstützung: nur JSON
                    continue
                raise self._error(e) from e
            except genai_errors.APIError as e:
                raise self._error(e) from e
        if stop in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
            raise LLMError("Gemini hat die Antwort aus Sicherheitsgründen blockiert.", "refusal")
        yield StreamEvent("done", usage=usage, stop_reason=stop, model=model)

    def _error(self, e: genai_errors.APIError) -> LLMError:
        code = getattr(e, "code", 0) or 0
        if code in (401, 403) or "api key" in str(e).lower():
            return LLMError("Gemini: API-Schlüssel ungültig oder ohne Berechtigung.", "auth")
        if code == 404:
            return LLMError(f"Gemini: Modell „{self.model}“ nicht gefunden.", "model")
        if code == 429:
            return LLMError("Gemini: Ratenlimit erreicht – bitte kurz warten.", "rate_limit")
        return LLMError(f"Gemini-Fehler {code}: {e}", "error")

    def list_models(self) -> list[str]:
        try:
            out = []
            for m in self.client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" in actions:
                    out.append(m.name.removeprefix("models/"))
            return sorted(out)
        except genai_errors.APIError:
            return []
