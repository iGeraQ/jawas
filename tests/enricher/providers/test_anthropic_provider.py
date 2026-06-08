import pytest
from unittest.mock import MagicMock, patch
from src.enricher.providers.anthropic import AnthropicProvider


def test_score_returns_int_from_haiku():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="8")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        score = provider.score("GPT-5 released", "Full article text...")
    assert score == 8


def test_score_returns_0_on_non_numeric_response():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="N/A")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        score = provider.score("Random title", "Random content")
    assert score == 0


def test_synthesize_returns_content_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="🚀 Big AI news!\n\n1/ Details here")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        drafts = provider.synthesize(
            title="GPT-5 Released",
            content="Full article content...",
            source_url="https://openai.com/gpt5",
            raw_content="Original post text",
            networks=["x"],
        )
    assert "x" in drafts
    assert len(drafts["x"]) > 0


def test_synthesize_calls_once_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Draft content")]
    )
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        provider.synthesize("t", "c", "u", "r", networks=["x", "linkedin"])
    assert mock_client.messages.create.call_count == 2


def test_synthesize_skips_network_on_api_error():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("src.enricher.providers.anthropic.anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicProvider()
        drafts = provider.synthesize("t", "c", "u", "r", networks=["x"])
    assert drafts == {}
