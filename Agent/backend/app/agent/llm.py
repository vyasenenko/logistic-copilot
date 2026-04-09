"""LLM provider factory — initializes the primary and fallback models."""

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from app.config import settings


def get_primary_llm() -> ChatAnthropic:
    """Return the primary LLM (Claude)."""
    return ChatAnthropic(
        model=settings.primary_model,
        api_key=settings.anthropic_api_key,
        max_tokens=8192,
        temperature=0.1,
        streaming=True,
    )


def get_fallback_llm() -> ChatOpenAI:
    """Return the fallback LLM (OpenAI) for cheaper/faster queries."""
    return ChatOpenAI(
        model=settings.fallback_model,
        api_key=settings.openai_api_key,
        max_tokens=4096,
        temperature=0.1,
        streaming=True,
    )
