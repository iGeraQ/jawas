from src.enricher.providers.base import AIProvider, AIProviderName, _REGISTRY, register


def get_provider() -> AIProvider:
    # Lazy imports so that loading this package does not trigger config initialization,
    # which would create a circular import (config → providers.base → providers.__init__
    # → anthropic/gemini → config).
    from src.enricher.providers.anthropic import AnthropicProvider  # noqa: F401 — triggers @register
    from src.enricher.providers.gemini import GeminiProvider  # noqa: F401 — triggers @register
    from src.enricher.providers.openai import OpenAIProvider  # noqa: F401 — triggers @register
    from src.shared.config import settings

    cls = _REGISTRY.get(settings.ai_provider)
    if not cls:
        raise ValueError(f"No provider registered for: {settings.ai_provider}")
    return cls()


__all__ = ["AIProvider", "AIProviderName", "get_provider", "register"]
