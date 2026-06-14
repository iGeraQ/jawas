from unittest.mock import MagicMock, patch

from src.enricher.content_extractor import extract_content


def test_extract_content_returns_text():
    mock_response = MagicMock()
    mock_response.text = "Article content here"
    mock_response.raise_for_status = MagicMock()

    with patch("src.enricher.content_extractor.httpx.get", return_value=mock_response), \
         patch("src.enricher.content_extractor.settings") as mock_settings:
        mock_settings.jina_api_key = "jina-test-key"
        result = extract_content("https://example.com/article")

    assert result == "Article content here"
