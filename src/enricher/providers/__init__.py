from src.enricher.providers.base import AIProvider, AIProviderName, _REGISTRY, register
from src.enricher.providers.anthropic import AnthropicProvider  # noqa: F401 — triggers @register
from src.enricher.providers.gemini import GeminiProvider  # noqa: F401 — triggers @register


def get_provider() -> AIProvider:
    from src.shared.config import settings
    cls = _REGISTRY.get(settings.ai_provider)
    if not cls:
        raise ValueError(f"No provider registered for: {settings.ai_provider}")
    return cls()


__all__ = ["AIProvider", "AIProviderName", "AnthropicProvider", "GeminiProvider", "get_provider", "register"]
