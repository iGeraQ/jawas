import pytest
from unittest.mock import patch
from src.enricher.providers import _REGISTRY, get_provider
from src.enricher.providers.base import AIProviderName
from src.enricher.providers.anthropic import AnthropicProvider
from src.enricher.providers.gemini import GeminiProvider


def test_registry_contains_anthropic():
    assert _REGISTRY.get(AIProviderName.ANTHROPIC) is AnthropicProvider


def test_registry_contains_gemini():
    assert _REGISTRY.get(AIProviderName.GEMINI) is GeminiProvider


def test_get_provider_raises_on_unknown():
    with patch("src.shared.config.settings") as mock_settings:
        mock_settings.ai_provider = "not_a_real_provider"
        with pytest.raises(ValueError, match="No provider registered"):
            get_provider()
