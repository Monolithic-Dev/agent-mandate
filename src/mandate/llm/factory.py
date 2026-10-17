"""Choosing a model from settings: ``MANDATE_LLM_PROVIDER`` and friends."""

from __future__ import annotations

from dataclasses import dataclass

from mandate.config import Settings
from mandate.errors import ConfigError
from mandate.llm.anthropic_chat import AnthropicChat
from mandate.llm.base import ChatModel
from mandate.llm.openai_chat import OpenAIChat


@dataclass(frozen=True)
class Preset:
    base_url: str | None
    default_model: str
    key_setting: str  # the Settings field that holds this provider's key


PRESETS: dict[str, Preset] = {
    "anthropic": Preset(None, "claude-sonnet-5-5", "anthropic_api_key"),
    "groq": Preset("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "groq_api_key"),
    "openai": Preset("https://api.openai.com/v1", "gpt-4.1", "openai_api_key"),
    # Any other OpenAI-compatible server: set MANDATE_LLM_BASE_URL (and a key if it needs one).
    "openai-compatible": Preset(None, "", "mandate_llm_api_key"),
}


def build_chat_model(
    settings: Settings, *, provider: str | None = None, model: str | None = None
) -> ChatModel:
    name = (provider or settings.mandate_llm_provider).lower()
    preset = PRESETS.get(name)
    if preset is None:
        raise ConfigError(f"unknown LLM provider {name!r}; choose from {sorted(PRESETS)}")
    configured = settings.mandate_model if name == "anthropic" else settings.mandate_llm_model
    chosen = model or configured or preset.default_model
    if not chosen:
        raise ConfigError(f"set MANDATE_MODEL for the {name!r} provider")
    secret = getattr(settings, preset.key_setting, None) or settings.mandate_llm_api_key
    key = secret.get_secret_value() if secret is not None else None
    if name == "anthropic":
        if not key:
            raise ConfigError("set ANTHROPIC_API_KEY to use the anthropic provider")
        return AnthropicChat(api_key=key, model=chosen)
    base = settings.mandate_llm_base_url or preset.base_url
    if not base:
        raise ConfigError("set MANDATE_LLM_BASE_URL for an openai-compatible provider")
    # A local server (Ollama, vLLM) may need no key; the hosted ones do.
    local = base.startswith(("http://localhost", "http://127.0.0.1"))
    if not key and not local:
        raise ConfigError(f"set the API key for the {name!r} provider (see .env.example)")
    return OpenAIChat(base_url=base, api_key=key, model=chosen)
