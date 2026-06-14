from unittest.mock import MagicMock, patch

from src.fetcher.sources.reddit import fetch_reddit_items


def test_fetch_reddit_no_credentials():
    with patch("src.fetcher.sources.reddit.settings") as mock_settings:
        mock_settings.reddit_client_id = ""
        result = fetch_reddit_items()
    assert result == []


def test_fetch_reddit_returns_items():
    mock_post = MagicMock()
    mock_post.id = "abc123"
    mock_post.title = "LLM benchmark results"
    mock_post.selftext = "Details about the benchmark"
    mock_post.permalink = "/r/MachineLearning/comments/abc123/llm_benchmark"

    mock_subreddit = MagicMock()
    mock_subreddit.hot.return_value.__getitem__ = lambda self, s: [mock_post][:4]
    mock_subreddit.hot.return_value = [mock_post]

    mock_reddit = MagicMock()
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("src.fetcher.sources.reddit.praw.Reddit", return_value=mock_reddit), \
         patch("src.fetcher.sources.reddit.settings") as mock_settings:
        mock_settings.reddit_client_id = "client-id"
        mock_settings.reddit_client_secret = "secret"
        mock_settings.reddit_user_agent = "jawas/1.0"
        mock_settings.reddit_subreddits = ["MachineLearning"]
        result = fetch_reddit_items()

    assert len(result) == 1
    assert result[0]["source"] == "reddit"
    assert "reddit.com" in result[0]["url"]
    assert result[0]["title"] == "LLM benchmark results"


def test_fetch_reddit_exception_returns_empty():
    with patch("src.fetcher.sources.reddit.praw.Reddit", side_effect=Exception("auth error")), \
         patch("src.fetcher.sources.reddit.settings") as mock_settings:
        mock_settings.reddit_client_id = "client-id"
        mock_settings.reddit_client_secret = "secret"
        mock_settings.reddit_user_agent = "jawas/1.0"
        mock_settings.reddit_subreddits = ["MachineLearning"]
        result = fetch_reddit_items()

    assert result == []
