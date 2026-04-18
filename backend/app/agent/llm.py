"""LLM provider router — selects providers by env-configured priority."""

from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from app.config import settings

SUPPORTED_PROVIDERS = ("deepseek", "openai", "anthropic")


def has_provider_config(provider: str) -> bool:
    provider = provider.strip().lower()
    if provider == "deepseek":
        return bool(settings.deepseek_api_key and settings.deepseek_model)
    if provider == "openai":
        return bool(settings.openai_api_key and settings.effective_openai_model)
    if provider == "anthropic":
        return bool(settings.anthropic_api_key and settings.effective_anthropic_model)
    return False


def get_configured_provider_order() -> list[str]:
    ordered = settings.configured_llm_provider_order or list(SUPPORTED_PROVIDERS)
    return [provider for provider in ordered if provider in SUPPORTED_PROVIDERS]


def get_available_provider_order() -> list[str]:
    return [provider for provider in get_configured_provider_order() if has_provider_config(provider)]


def get_llm_for_provider(
    provider: str,
    *,
    max_tokens: int | None = None,
    streaming: bool = True,
) -> Any:
    provider = provider.strip().lower()
    token_limit = max_tokens or settings.llm_primary_max_tokens

    if provider == "deepseek":
        if not has_provider_config(provider):
            raise RuntimeError("DeepSeek provider is not configured")
        return ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            max_tokens=token_limit,
            temperature=settings.llm_temperature,
            streaming=streaming,
        )

    if provider == "openai":
        if not has_provider_config(provider):
            raise RuntimeError("OpenAI provider is not configured")
        return ChatOpenAI(
            model=settings.effective_openai_model,
            api_key=settings.openai_api_key,
            max_tokens=token_limit,
            temperature=settings.llm_temperature,
            streaming=streaming,
        )

    if provider == "anthropic":
        if not has_provider_config(provider):
            raise RuntimeError("Anthropic provider is not configured")
        return ChatAnthropic(
            model=settings.effective_anthropic_model,
            api_key=settings.anthropic_api_key,
            max_tokens=token_limit,
            temperature=settings.llm_temperature,
            streaming=streaming,
        )

    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def get_primary_llm() -> Any:
    """Return the first configured provider from llm_provider_order."""
    available = get_available_provider_order()
    if not available:
        raise RuntimeError("No configured LLM providers available")
    return get_llm_for_provider(
        available[0],
        max_tokens=settings.llm_primary_max_tokens,
        streaming=True,
    )


def get_fallback_llm() -> Any:
    """Return the next configured provider from llm_provider_order."""
    available = get_available_provider_order()
    if not available:
        raise RuntimeError("No configured LLM providers available")
    provider = available[1] if len(available) > 1 else available[0]
    return get_llm_for_provider(
        provider,
        max_tokens=settings.llm_fallback_max_tokens,
        streaming=True,
    )


def try_get_primary_llm() -> Any | None:
    """Return the first configured LLM or None when no provider is configured."""
    try:
        return get_primary_llm()
    except RuntimeError:
        return None
