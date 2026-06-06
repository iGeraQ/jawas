from unittest.mock import patch, MagicMock
from src.publisher.providers.x import XProvider


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
