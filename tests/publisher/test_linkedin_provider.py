from unittest.mock import MagicMock, patch

import pytest

from src.publisher.base import PublishResult


def test_publishes_post_and_returns_result():
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.headers = {"x-restli-id": "urn:li:share:7123456789"}

    with patch("src.publisher.providers.linkedin.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.linkedin.settings") as mock_settings:
        mock_settings.linkedin_access_token = "token123"
        mock_settings.linkedin_author_urn = "urn:li:organization:999"

        from src.publisher.providers.linkedin import LinkedInProvider
        provider = LinkedInProvider()
        result = provider.publish("Great AI news!")

    assert result.post_id == "urn:li:share:7123456789"
    assert "urn:li:share:7123456789" in result.url
    assert result.post_count == 1


def test_raises_on_api_error_with_linkedin_body():
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 422
    mock_response.text = '{"serviceErrorCode":65600,"message":"Unknown author","status":422}'

    with patch("src.publisher.providers.linkedin.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.linkedin.settings") as mock_settings:
        mock_settings.linkedin_access_token = "token123"
        mock_settings.linkedin_author_urn = "urn:li:organization:999"

        from src.publisher.providers.linkedin import LinkedInProvider
        provider = LinkedInProvider()
        with pytest.raises(ValueError, match="422"):
            provider.publish("Some content")


def test_raises_when_author_urn_not_configured():
    with patch("src.publisher.providers.linkedin.settings") as mock_settings:
        mock_settings.linkedin_access_token = "token123"
        mock_settings.linkedin_author_urn = ""

        from src.publisher.providers.linkedin import LinkedInProvider
        provider = LinkedInProvider()
        with pytest.raises(ValueError, match="LINKEDIN_AUTHOR_URN"):
            provider.publish("Some content")


def test_truncates_content_over_3000_chars():
    long_content = "A" * 3500
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.headers = {"x-restli-id": "urn:li:share:9999"}

    with patch("src.publisher.providers.linkedin.httpx.post", return_value=mock_response) as mock_post, \
         patch("src.publisher.providers.linkedin.settings") as mock_settings:
        mock_settings.linkedin_access_token = "tok"
        mock_settings.linkedin_author_urn = "urn:li:organization:1"

        from src.publisher.providers.linkedin import LinkedInProvider
        provider = LinkedInProvider()
        provider.publish(long_content)

    posted_text = mock_post.call_args[1]["json"]["specificContent"][
        "com.linkedin.ugc.ShareContent"
    ]["shareCommentary"]["text"]
    assert len(posted_text) == 3000
