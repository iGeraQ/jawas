import pytest

from src.publisher.base import (
    PublishResult,
    RateLimitExceeded,
    SocialNetworkProvider,
    get_provider,
    register_publisher,
    split_into_thread,
)


def test_split_short_text_is_single_chunk():
    assert split_into_thread("hello world", 280) == ["hello world"]


def test_split_keeps_short_multipart_as_one_chunk():
    text = "Tweet 1\n\nTweet 2\n\nTweet 3"
    assert split_into_thread(text, 280) == [text]


def test_split_long_text_into_bounded_chunks_without_losing_words():
    text = " ".join(["word"] * 200)  # 999 chars
    chunks = split_into_thread(text, 100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    # Every original word survives, in order.
    assert " ".join(chunks).split() == text.split()


def test_split_hard_splits_token_longer_than_limit():
    url = "https://example.com/" + "a" * 100  # 120 chars, no spaces
    chunks = split_into_thread(url, 50)
    assert all(len(c) <= 50 for c in chunks)
    assert "".join(chunks) == url


def test_publish_result_default_post_count():
    result = PublishResult(post_id="abc", url="https://example.com/abc")
    assert result.post_count == 1


def test_publish_result_stores_all_fields():
    result = PublishResult(post_id="abc", url="https://example.com/abc", post_count=3)
    assert result.post_id == "abc"
    assert result.url == "https://example.com/abc"
    assert result.post_count == 3


def test_rate_limit_exceeded_stores_wait():
    exc = RateLimitExceeded(wait_seconds=7200)
    assert exc.wait_seconds == 7200


def test_register_and_get_provider():
    @register_publisher("_test_network_abc")
    class _TestProvider(SocialNetworkProvider):
        def publish(self, content: str) -> PublishResult:
            return PublishResult(post_id="t1", url="https://test.net/t1")

    provider = get_provider("_test_network_abc")
    assert isinstance(provider, _TestProvider)


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown publisher"):
        get_provider("_nonexistent_xyz_abc_123")
