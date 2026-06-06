from unittest.mock import patch, MagicMock
from src.enricher.synthesizer import generate_drafts

def test_generate_drafts_returns_content_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="🚀 Big AI news! Thread below...\n\n1/ Details here")]
    )
    with patch("src.enricher.synthesizer._client", mock_client):
        drafts = generate_drafts(
            title="GPT-5 Released",
            content="Full article content...",
            source_url="https://openai.com/gpt5",
            raw_content="Original post text",
            networks=["x"],
        )
    assert "x" in drafts
    assert len(drafts["x"]) > 0

def test_generate_drafts_calls_once_per_network():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Draft content")]
    )
    with patch("src.enricher.synthesizer._client", mock_client):
        generate_drafts("t", "c", "u", "r", networks=["x", "linkedin"])
    assert mock_client.messages.create.call_count == 2

def test_generate_drafts_skips_network_on_api_error():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("rate limit")
    with patch("src.enricher.synthesizer._client", mock_client):
        drafts = generate_drafts("t", "c", "u", "r", networks=["x"])
    assert drafts == {}
