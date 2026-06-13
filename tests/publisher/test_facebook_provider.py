from unittest.mock import MagicMock, patch

import pytest

from src.publisher.base import PublishResult


def test_publishes_post_and_returns_result():
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "123456789_987654321"}
    mock_response.raise_for_status = MagicMock()

    with patch("src.publisher.providers.facebook.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.facebook.settings") as mock_settings:
        mock_settings.facebook_page_id = "123456789"
        mock_settings.facebook_page_access_token = "EAAtoken"

        from src.publisher.providers.facebook import FacebookProvider
        provider = FacebookProvider()
        result = provider.publish("Check out this AI news!")

    assert result.post_id == "123456789_987654321"
    assert "123456789" in result.url
    assert "987654321" in result.url
    assert result.post_count == 1


def test_url_contains_object_id_not_full_id():
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "111_222"}
    mock_response.raise_for_status = MagicMock()

    with patch("src.publisher.providers.facebook.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.facebook.settings") as mock_settings:
        mock_settings.facebook_page_id = "111"
        mock_settings.facebook_page_access_token = "tok"

        from src.publisher.providers.facebook import FacebookProvider
        provider = FacebookProvider()
        result = provider.publish("Hello Facebook!")

    assert result.url == "https://www.facebook.com/111/posts/222"


def test_raises_on_api_error():
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("400 Bad Request")

    with patch("src.publisher.providers.facebook.httpx.post", return_value=mock_response), \
         patch("src.publisher.providers.facebook.settings") as mock_settings:
        mock_settings.facebook_page_id = "123"
        mock_settings.facebook_page_access_token = "bad"

        from src.publisher.providers.facebook import FacebookProvider
        provider = FacebookProvider()
        with pytest.raises(Exception, match="400"):
            provider.publish("Some content")
