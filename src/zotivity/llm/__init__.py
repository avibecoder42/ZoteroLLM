"""Anbieterneutrale LLM-Schicht."""

from __future__ import annotations

from zotivity.catalog import PROVIDERS
from zotivity.keystore import get_store
from zotivity.llm.base import (
    ChatMessage,
    ChatModel,
    Completion,
    GenParams,
    LLMError,
    StreamEvent,
    Usage,
    UsageMeter,
    parse_json,
    retry_after_truncation,
    truncation,
)
from zotivity.settings import LLMSettings


def base_url_for(provider: str, cfg: LLMSettings) -> str | None:
    url = cfg.base_urls.get(provider) or PROVIDERS.get(provider, None) and PROVIDERS[provider].default_base_url
    if not url:
        return None
    url = url.rstrip("/")
    if provider == "ollama" and not url.endswith("/v1"):
        url += "/v1"
    return url


def make_chat_model(provider: str, model: str, cfg: LLMSettings, meter: UsageMeter | None = None) -> ChatModel:
    key = get_store().get(provider)
    timeout = cfg.request_timeout
    if provider == "anthropic":
        from zotivity.llm.anthropic_provider import AnthropicChat

        return AnthropicChat(model, key, timeout=timeout, meter=meter)
    if provider == "gemini":
        from zotivity.llm.gemini_provider import GeminiChat

        return GeminiChat(model, key, timeout=timeout, meter=meter)
    if provider in ("openai", "deepseek", "ollama", "openai_compatible"):
        from zotivity.llm.openai_provider import OpenAIChat

        return OpenAIChat(model, key, provider=provider, base_url=base_url_for(provider, cfg), timeout=timeout,
                          meter=meter)
    raise LLMError(f"Unbekannter Anbieter: {provider}")


def main_model(cfg: LLMSettings, meter: UsageMeter | None = None) -> ChatModel:
    return make_chat_model(cfg.provider, cfg.model, cfg, meter)


def helper_model(cfg: LLMSettings, meter: UsageMeter | None = None) -> ChatModel:
    if not cfg.helper_model:
        return main_model(cfg, meter)
    return make_chat_model(cfg.helper_provider or cfg.provider, cfg.helper_model, cfg, meter)


__all__ = [
    "ChatMessage",
    "ChatModel",
    "Completion",
    "GenParams",
    "LLMError",
    "StreamEvent",
    "Usage",
    "UsageMeter",
    "helper_model",
    "main_model",
    "make_chat_model",
    "parse_json",
    "retry_after_truncation",
    "truncation",
]
