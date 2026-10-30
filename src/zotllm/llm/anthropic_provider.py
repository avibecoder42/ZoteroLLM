"""Claude über das offizielle Anthropic-SDK."""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator

import anthropic

from zotllm.llm.base import ChatMessage, ChatModel, GenParams, LLMError, StreamEvent, Usage

# Modelle, die serverseitige Fallbacks bei Ablehnungen durch Sicherheitsklassifikatoren unterstützen
_FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _version(model: str) -> tuple[int, int] | None:
    m = re.match(r"claude-(?:opus|sonnet|haiku)-(\d+)(?:-(\d+))?", model)
    if not m:
        return None
    minor = int(m.group(2) or 0)
    if minor > 99:  # Datumssuffix wie claude-opus-4-20250514
        minor = 0
    return int(m.group(1)), minor


def supports_sampling(model: str) -> bool:
    """temperature/top_p werden ab Opus 4.7 bzw. den 5er-Modellen abgelehnt."""
    if model.startswith("claude-3"):
        return True
    v = _version(model)
    return v is not None and (v[0] < 4 or (v[0] == 4 and v[1] <= 6))


def supports_structured_output(model: str) -> bool:
    """JSON-Antwort nach Schema (output_config.format): Fable/Mythos, die 5er-Modelle, Opus 4.8/4.5/4.1, Haiku 4.5."""
    if model.startswith(("claude-fable", "claude-mythos")):
        return True
    v = _version(model)
    if v is None:
        return False
    return v[0] >= 5 or (v[0] == 4 and ("opus" in model and v[1] in (1, 5, 8) or "haiku" in model and v[1] == 5))


def supports_effort(model: str) -> bool:
    if model.startswith(("claude-fable", "claude-mythos")):
        return True
    v = _version(model)
    if v is None:
        return False
    if v[0] >= 5:
        return True
    return v[0] == 4 and (v[1] >= 6 or (v[1] == 5 and "opus" in model))


class AnthropicChat(ChatModel):
    provider = "anthropic"

    def __init__(self, model: str, api_key: str, timeout: float = 600.0, meter=None):
        super().__init__(model, meter)
        if not api_key:
            raise LLMError("Kein Anthropic-API-Schlüssel gespeichert.", "auth")
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=3)

    def _messages(self, messages: list[ChatMessage]) -> list[dict]:
        out = []
        for m in messages:
            if m.images:
                content = [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png",
                                   "data": base64.standard_b64encode(img).decode("ascii")},
                    }
                    for img in m.images
                ]
                content.append({"type": "text", "text": m.content})
                out.append({"role": m.role, "content": content})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def _stream(self, system: str, messages: list[ChatMessage], params: GenParams) -> Iterator[StreamEvent]:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": params.max_tokens,
            "messages": self._messages(messages),
            # Automatisches Prompt-Caching: spart bei Folgefragen und langen Kontexten
            "cache_control": {"type": "ephemeral"},
        }
        if system:
            kwargs["system"] = system
        output_config: dict = {}
        if params.effort and supports_effort(self.model):
            output_config["effort"] = params.effort
        if params.json_mode and params.json_schema and supports_structured_output(self.model):
            output_config["format"] = {"type": "json_schema", "schema": params.json_schema}
        if output_config:
            kwargs["output_config"] = output_config
        if params.temperature is not None and supports_sampling(self.model):
            kwargs["temperature"] = params.temperature

        use_fallback = self.model in _FALLBACK_MODELS
        try:
            if use_fallback:
                ctx = self.client.beta.messages.stream(betas=[_FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                ctx = self.client.messages.stream(**kwargs)
            with ctx as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield StreamEvent("text", text=event.delta.text)
                final = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMError("Anthropic: API-Schlüssel ungültig.", "auth") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError(f"Anthropic: keine Berechtigung ({e.message}).", "auth") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Anthropic: Modell „{self.model}“ nicht gefunden.", "model") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic: Ratenlimit erreicht – bitte kurz warten.", "rate_limit") from e
        except anthropic.BadRequestError as e:
            kind = "context" if "too long" in str(e.message).lower() else "error"
            raise LLMError(f"Anthropic: ungültige Anfrage – {e.message}", kind) from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Anthropic: keine Verbindung.", "connection") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic-Fehler {e.status_code}: {e.message}", "error") from e

        if final.stop_reason == "refusal":
            details = getattr(final, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMError(
                "Claude hat die Anfrage aus Sicherheitsgründen abgelehnt"
                + (f" (Kategorie: {category})." if category else "."),
                "refusal",
            )
        u = final.usage
        usage = Usage(
            input_tokens=(u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
            + (getattr(u, "cache_read_input_tokens", 0) or 0),
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            requests=1,
        )
        yield StreamEvent("done", usage=usage, stop_reason=final.stop_reason or "", model=final.model)

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self.client.models.list()]
        except anthropic.APIError:
            return []
