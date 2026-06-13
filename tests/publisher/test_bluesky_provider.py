from unittest.mock import MagicMock, patch

import pytest

from src.publisher.base import PublishResult, RateLimitExceeded


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

    mock_instance.send_post.assert_called_once_with(text="Hello Bluesky!", reply_to=None)
    assert result.post_id == "at://did:plc:abc123/app.bsky.feed.post/rkey42"
    assert "rkey42" in result.url
    assert "testuser.bsky.social" in result.url
    assert result.post_count == 1


def test_thread_posts_chain_correctly():
    call_count = 0
    uris = [
        "at://did:plc:abc/app.bsky.feed.post/rkey1",
        "at://did:plc:abc/app.bsky.feed.post/rkey2",
    ]

    def fake_send_post(text, reply_to=None):
        nonlocal call_count
        resp = MagicMock()
        resp.uri = uris[call_count]
        resp.cid = f"cid{call_count}"
        call_count += 1
        return resp

    with patch("src.publisher.providers.bluesky.Client") as MockClient, \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "testuser.bsky.social"
        mock_settings.bluesky_app_password = "app-pass"
        mock_instance = MockClient.return_value
        mock_instance.send_post.side_effect = fake_send_post

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        result = provider.publish("Post one\n\nPost two")

    assert mock_instance.send_post.call_count == 2
    assert result.post_id == uris[0]
    assert result.post_count == 2
    # Second call must have a reply_to set (it's chaining)
    second_kwargs = mock_instance.send_post.call_args_list[1][1]
    assert second_kwargs["reply_to"] is not None


def test_empty_content_raises():
    with patch("src.publisher.providers.bluesky.Client"), \
         patch("src.publisher.providers.bluesky.settings") as mock_settings:
        mock_settings.bluesky_handle = "h"
        mock_settings.bluesky_app_password = "p"

        from src.publisher.providers.bluesky import BlueskyProvider
        provider = BlueskyProvider()
        with pytest.raises(ValueError, match="Empty content"):
            provider.publish("   ")
