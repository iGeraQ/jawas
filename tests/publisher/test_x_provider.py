import pytest
import tweepy
from unittest.mock import patch, MagicMock

from src.publisher.providers.x import DailyLimitReached, XProvider
from src.publisher.main import process_message
from src.shared.config import settings as _settings


def test_publishes_single_tweet():
    mock_client = MagicMock()
    mock_client.create_tweet.return_value = MagicMock(data={"id": "tweet123"})
    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client):
        provider = XProvider()
        result = provider.publish("Short tweet content")
    mock_client.create_tweet.assert_called_once_with(text="Short tweet content")
    assert result == "tweet123"


def test_publishes_thread_for_multipart_content():
    call_count = 0

    def fake_create_tweet(**kwargs):
        nonlocal call_count
        call_count += 1
        return MagicMock(data={"id": f"t{call_count}"})

    mock_client = MagicMock()
    mock_client.create_tweet.side_effect = fake_create_tweet

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client):
        provider = XProvider()
        result = provider.publish("Tweet 1\n\nTweet 2\n\nTweet 3")

    assert mock_client.create_tweet.call_count == 3
    assert result == "t1"
    # Verify thread chaining
    calls = mock_client.create_tweet.call_args_list
    assert "in_reply_to_tweet_id" not in calls[0].kwargs
    assert calls[1].kwargs.get("in_reply_to_tweet_id") == "t1"
    assert calls[2].kwargs.get("in_reply_to_tweet_id") == "t2"


def test_429_does_not_retry():
    mock_response = MagicMock()
    mock_response.headers = {"x-rate-limit-reset": "9999999999"}
    mock_response.status_code = 429
    mock_response.json.return_value = {"errors": []}

    mock_client = MagicMock()
    mock_client.create_tweet.side_effect = tweepy.errors.TooManyRequests(mock_response)

    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client):
        provider = XProvider()
        with pytest.raises(tweepy.errors.TooManyRequests):
            provider._post_tweet("test tweet")

    assert mock_client.create_tweet.call_count == 1  # not retried by tenacity


def test_daily_limit_check_blocks_publish():
    """process_message raises DailyLimitReached without calling tweepy when quota is exhausted."""
    mock_draft = MagicMock()
    mock_draft.id = "draft-uuid"
    mock_draft.network = "x"
    mock_draft.content = "Tweet 1\n\nTweet 2\n\nTweet 3"  # 3 tweets
    mock_draft.edited_content = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_draft
    # Idempotency check: not yet published
    mock_session.execute.return_value.scalar_one_or_none.return_value = None
    # Daily limit: 14 used + 3 new = 17 > 15 → should block
    mock_session.scalar.return_value = 14

    mock_tweepy_client = MagicMock()

    with patch("src.publisher.main.get_session", return_value=mock_session), \
         patch("src.publisher.providers.x.tweepy.Client", return_value=mock_tweepy_client), \
         patch.object(_settings, "x_tweets_per_day", 15):
        with pytest.raises(DailyLimitReached) as exc_info:
            process_message({"draft_id": "draft-uuid", "network": "x"}, "x")

    assert exc_info.value.used == 14
    assert exc_info.value.limit == 15
    mock_tweepy_client.create_tweet.assert_not_called()
    mock_session.rollback.assert_called_once()


def test_tweet_count_stored_on_publish():
    """PublishedPost is created with post_count equal to the number of content paragraphs."""
    mock_draft = MagicMock()
    mock_draft.id = "draft-uuid"
    mock_draft.network = "x"
    mock_draft.content = "Tweet 1\n\nTweet 2"  # 2 tweets
    mock_draft.edited_content = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_draft
    mock_session.execute.return_value.scalar_one_or_none.return_value = None
    mock_session.scalar.return_value = 0  # 0 used, 2 new = 2 <= 15 → ok

    mock_provider = MagicMock()
    mock_provider.publish.return_value = "tweet_id_1"

    with patch("src.publisher.main.get_session", return_value=mock_session), \
         patch("src.publisher.main.PROVIDERS", {"x": MagicMock(return_value=mock_provider)}), \
         patch.object(_settings, "x_tweets_per_day", 15):
        process_message({"draft_id": "draft-uuid", "network": "x"}, "x")

    added = mock_session.add.call_args[0][0]
    assert added.post_count == 2
