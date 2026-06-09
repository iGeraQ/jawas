from unittest.mock import MagicMock, patch
from src.fetcher.main import run_fetch_cycle


def test_fetch_cycle_caps_enqueued_items():
    """Only FETCHER_MAX_ITEMS_PER_CYCLE items should be enqueued per cycle."""
    items = [
        {
            "external_id": f"id{i}",
            "source": "rss",
            "url": f"https://example.com/{i}",
            "title": f"Title {i}",
        }
        for i in range(20)
    ]
    mock_session = MagicMock()
    with patch("src.fetcher.main.fetch_rss_items", return_value=items), \
         patch("src.fetcher.main.fetch_hn_items", return_value=[]), \
         patch("src.fetcher.main.fetch_reddit_items", return_value=[]), \
         patch("src.fetcher.main.fetch_x_items", return_value=[]), \
         patch("src.fetcher.main.get_session", return_value=mock_session), \
         patch("src.fetcher.main.filter_new_items", return_value=items), \
         patch("src.fetcher.main.send_message") as mock_send:
        run_fetch_cycle()
    assert mock_send.call_count == 10
