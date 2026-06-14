from unittest.mock import MagicMock, patch

import pytest

from src.publisher.base import PublishResult, RateLimitExceeded
from src.publisher.providers.bluesky import _build_facets


def test_single_post_returns_publish_result():
    mock_response = MagicMock()
    mock_response.uri = "at://did:plc:abc123/app.bsky.feed.post/rkey42"
    mock_response.cid = "bafy123"

    with patch("src.publisher.providers.bluesky.Client") as MockClient, \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "testuser.bsky.social"
        mock_settings.bluesky_app_password = "app-pass"
        mock_instance = MockClient.return_value
        mock_instance.send_post.return_value = mock_response

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        result = provider.publish("Hello Bluesky!")

    mock_instance.send_post.assert_called_once_with(text="Hello Bluesky!", facets=None)
    assert result.post_id == "at://did:plc:abc123/app.bsky.feed.post/rkey42"
    assert "rkey42" in result.url
    assert "testuser.bsky.social" in result.url
    assert result.post_count == 1


def test_single_post_for_multipart_content():
    mock_response = MagicMock()
    mock_response.uri = "at://did:plc:abc123/app.bsky.feed.post/rkey1"

    with patch("src.publisher.providers.bluesky.Client") as MockClient, \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "testuser.bsky.social"
        mock_settings.bluesky_app_password = "app-pass"
        mock_instance = MockClient.return_value
        mock_instance.send_post.return_value = mock_response

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        result = provider.publish("Post one\n\nPost two")

    mock_instance.send_post.assert_called_once_with(text="Post one\n\nPost two", facets=None)
    assert result.post_id == mock_response.uri
    assert result.post_count == 1


def test_empty_content_raises():
    with patch("src.publisher.providers.bluesky.Client"), \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "h"
        mock_settings.bluesky_app_password = "p"

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        with pytest.raises(ValueError, match="Empty content"):
            provider.publish("   ")


def test_url_in_content_creates_facets():
    mock_response = MagicMock()
    mock_response.uri = "at://did:plc:abc123/app.bsky.feed.post/rkey99"

    with patch("src.publisher.providers.bluesky.Client") as MockClient, \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "testuser.bsky.social"
        mock_settings.bluesky_app_password = "app-pass"
        mock_instance = MockClient.return_value
        mock_instance.send_post.return_value = mock_response

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        provider.publish("Revisa esto: https://example.com")

    call_kwargs = mock_instance.send_post.call_args[1]
    assert call_kwargs["text"] == "Revisa esto: https://example.com"
    facets = call_kwargs["facets"]
    assert facets is not None and len(facets) == 1
    assert facets[0].features[0].uri == "https://example.com"


def test_build_facets_byte_offsets_with_unicode():
    text = "Información: https://example.com fin."
    facets = _build_facets(text)

    assert len(facets) == 1
    uri = facets[0].features[0].uri
    assert uri == "https://example.com"

    # Verify byte offsets match the URL position in UTF-8 encoded text
    text_bytes = text.encode('utf-8')
    byte_start = facets[0].index.byte_start
    byte_end = facets[0].index.byte_end
    assert text_bytes[byte_start:byte_end] == b"https://example.com"


def test_build_facets_strips_trailing_punctuation():
    text = "Ver: https://example.com."
    facets = _build_facets(text)

    assert len(facets) == 1
    assert facets[0].features[0].uri == "https://example.com"


def test_build_facets_no_urls_returns_empty():
    facets = _build_facets("Sin URLs aquí.")
    assert facets == []
