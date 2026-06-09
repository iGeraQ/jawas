from unittest.mock import MagicMock, patch
from src.enricher.providers.gemini import GeminiProvider


def test_gemini_score_returns_int():
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text="7")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        score = provider.score("AI news title", "Article content here")
    assert score == 7


def test_gemini_score_returns_0_on_error():
    mock_model = MagicMock()
    mock_model.generate_content.side_effect = Exception("API error")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        score = provider.score("title", "content")
    assert score == 0


def test_gemini_synthesize_returns_content_per_network():
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text="Tweet draft content")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        drafts = provider.synthesize("Title", "Content", "http://url.com", "raw", ["x"])
    assert "x" in drafts
    assert drafts["x"] == "Tweet draft content"


def test_gemini_synthesize_skips_network_on_error():
    mock_model = MagicMock()
    mock_model.generate_content.side_effect = Exception("API error")
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model):
        provider = GeminiProvider()
        drafts = provider.synthesize("t", "c", "u", "r", ["x"])
    assert drafts == {}


def test_score_retries_on_resource_exhausted():
    from google.api_core.exceptions import ResourceExhausted
    mock_model = MagicMock()
    mock_model.generate_content.side_effect = [
        ResourceExhausted("quota exceeded"),
        MagicMock(text="8"),
    ]
    with patch("src.enricher.providers.gemini.genai.configure"), \
         patch("src.enricher.providers.gemini.genai.GenerativeModel", return_value=mock_model), \
         patch("src.enricher.providers.gemini.TokenBucket.acquire"), \
         patch("time.sleep"):
        provider = GeminiProvider()
        score = provider.score("title", "content")
    assert score == 8
    assert mock_model.generate_content.call_count == 2
