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
    mock_client = MagicMock()
    mock_client.create_tweet.return_value = MagicMock(data={"id": "t1"})
    with patch("src.publisher.providers.x.tweepy.Client", return_value=mock_client):
        provider = XProvider()
        provider.publish("Tweet 1\n\nTweet 2\n\nTweet 3")
    assert mock_client.create_tweet.call_count == 3
