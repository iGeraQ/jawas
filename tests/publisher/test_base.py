import pytest

from src.publisher.base import (
    PublishResult,
    RateLimitExceeded,
    SocialNetworkProvider,
    get_provider,
    register_publisher,
)


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
