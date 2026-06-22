import itertools

import pytest
import tweepy
from unittest.mock import patch, MagicMock

from src.publisher.providers.x import XProvider
from src.publisher.base import PublishResult, RateLimitExceeded
from src.publisher.main import process_message
from src.shared.config import settings as _settings


def test_publishes_single_tweet():
    mock_client = MagicMock()
    mock_client.create_tweet.return_value = MagicMock(data={"id": "tweet123"})
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0  # 0 tweets used in last 24h

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session):
        provider = XProvider()
        result = provider.publish("Short tweet content")

    mock_client.create_tweet.assert_called_once_with(text="Short tweet content")
    assert result.post_id == "tweet123"
    assert result.url == "https://x.com/i/web/status/tweet123"
    assert result.post_count == 1


def test_publishes_multipart_as_single_tweet():
    mock_client = MagicMock()
    mock_client.create_tweet.return_value = MagicMock(data={"id": "tweet123"})
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session):
        provider = XProvider()
        result = provider.publish("Tweet 1\n\nTweet 2\n\nTweet 3")

    mock_client.create_tweet.assert_called_once_with(text="Tweet 1\n\nTweet 2\n\nTweet 3")
    assert result.post_id == "tweet123"
    assert result.post_count == 1


def test_publishes_long_content_as_thread():
    counter = itertools.count(1)
    mock_client = MagicMock()
    mock_client.create_tweet.side_effect = lambda **kw: MagicMock(data={"id": f"t{next(counter)}"})
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0

    long_content = " ".join(["word"] * 300)  # ~1499 chars → several tweets at 280

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session):
        provider = XProvider()
        result = provider.publish(long_content)

    n = mock_client.create_tweet.call_count
    assert n >= 2
    calls = mock_client.create_tweet.call_args_list
    # Root tweet has no reply target; each subsequent tweet chains to the prior id.
    assert "in_reply_to_tweet_id" not in calls[0].kwargs
    assert calls[1].kwargs["in_reply_to_tweet_id"] == "t1"
    assert calls[2].kwargs["in_reply_to_tweet_id"] == "t2"
    assert all(len(c.kwargs["text"]) <= 280 for c in calls)
    assert result.post_id == "t1"
    assert result.post_count == n


def test_429_does_not_retry():
    mock_response = MagicMock()
    mock_response.headers = {"x-rate-limit-reset": "9999999999"}
    mock_response.status_code = 429
    mock_response.json.return_value = {"errors": []}

    mock_client = MagicMock()
    mock_client.create_tweet.side_effect = tweepy.errors.TooManyRequests(mock_response)
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session):
        provider = XProvider()
        with pytest.raises(tweepy.errors.TooManyRequests):
            provider._post_tweet("test tweet")

    assert mock_client.create_tweet.call_count == 1


def test_daily_limit_check_raises_rate_limit_exceeded():
    """XProvider.publish raises RateLimitExceeded when daily quota is exhausted."""
    mock_session = MagicMock()
    # First scalar call: 15 used. Second: None (no oldest post found).
    mock_session.scalar.side_effect = [15, None]

    with patch("src.publisher.providers.x.tweepy.Client", return_value=MagicMock()), \
         patch("src.publisher.providers.x.get_session", return_value=mock_session), \
         patch.object(_settings, "x_tweets_per_day", 15):
        provider = XProvider()
        with pytest.raises(RateLimitExceeded) as exc_info:
            provider.publish("Tweet content")  # 1 tweet, 15+1=16>15

    assert exc_info.value.wait_seconds >= 60
    mock_session.close.assert_called_once()


def test_post_count_stored_on_publish():
    """PublishedPost is created with post_count matching the number of paragraphs."""
    mock_draft = MagicMock()
    mock_draft.id = "draft-uuid"
    mock_draft.network = "x"
    mock_draft.content = "Tweet 1\n\nTweet 2"
    mock_draft.edited_content = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_draft
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    mock_provider = MagicMock()
    mock_provider.publish.return_value = PublishResult(
        post_id="tweet_id_1",
        url="https://x.com/i/web/status/tweet_id_1",
        post_count=1,
    )

    with patch("src.publisher.main.get_session", return_value=mock_session), \
         patch("src.publisher.main.get_provider", return_value=mock_provider):
        process_message({"draft_id": "draft-uuid", "network": "x"}, "x")

    added = mock_session.add.call_args[0][0]
    assert added.post_count == 1
    assert added.url == "https://x.com/i/web/status/tweet_id_1"
    assert added.network_post_id == "tweet_id_1"
