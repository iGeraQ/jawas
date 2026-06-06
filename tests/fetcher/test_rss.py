from unittest.mock import patch, MagicMock
from src.fetcher.sources.rss import fetch_rss_items


def test_fetch_rss_returns_items():
    mock_feed = MagicMock()
    mock_feed.entries = [
        MagicMock(
            title="New Claude Model",
            link="https://anthropic.com/news/claude",
            summary="Anthropic releases...",
        )
    ]
    with patch("src.fetcher.sources.rss.feedparser.parse", return_value=mock_feed):
        items = fetch_rss_items(["https://anthropic.com/rss.xml"])
    assert len(items) == 1
    assert items[0]["title"] == "New Claude Model"
    assert items[0]["source"] == "rss"


def test_fetch_rss_skips_entries_without_link():
    mock_feed = MagicMock()
    mock_feed.entries = [MagicMock(title="No link", link="", summary="")]
    with patch("src.fetcher.sources.rss.feedparser.parse", return_value=mock_feed):
        items = fetch_rss_items(["https://example.com/rss.xml"])
    assert items == []
