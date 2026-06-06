from unittest.mock import patch, MagicMock
from src.enricher.scorer import score_relevance

def test_score_returns_int_from_haiku():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="8")]
    )
    with patch("src.enricher.scorer._client", mock_client):
        score = score_relevance("GPT-5 released", "Full article text...")
    assert score == 8

def test_score_returns_0_on_non_numeric_response():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="N/A")]
    )
    with patch("src.enricher.scorer._client", mock_client):
        score = score_relevance("Random title", "Random content")
    assert score == 0
