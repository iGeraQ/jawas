from unittest.mock import MagicMock, patch
import structlog
import structlog.testing
import pytest


@pytest.fixture(autouse=True)
def reset_structlog():
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def _make_raw_item(n: int) -> dict:
    return {
        "external_id": f"id-{n}",
        "source": "rss",
        "url": f"http://example.com/{n}",
        "title": f"Title {n}",
        "raw_content": "",
    }


def test_run_fetch_cycle_emits_dedup_stats():
    from src.fetcher.main import run_fetch_cycle

    items = [_make_raw_item(i) for i in range(3)]

    with patch("src.fetcher.main.fetch_rss_items", return_value=items), \
         patch("src.fetcher.main.fetch_hn_items", return_value=[]), \
         patch("src.fetcher.main.fetch_reddit_items", return_value=[]), \
         patch("src.fetcher.main.fetch_x_items", return_value=[]), \
         patch("src.fetcher.main.filter_new_items", return_value=items[:2]), \
         patch("src.fetcher.main.get_session") as mock_session, \
         patch("src.fetcher.main.send_message"), \
         patch("src.fetcher.main.settings") as mock_settings:

        mock_settings.fetcher_max_items_per_cycle = 10
        mock_settings.raw_items_queue_url = "http://q"
        session = MagicMock()
        session.flush = MagicMock()
        mock_session.return_value = session

        with structlog.testing.capture_logs() as cap_logs:
            run_fetch_cycle()

    dedup_events = [l for l in cap_logs if l.get("event") == "dedup_stats"]
    assert len(dedup_events) == 1
    assert dedup_events[0]["total"] == 3
    assert dedup_events[0]["new"] == 2
    assert dedup_events[0]["duplicates"] == 1


def test_run_fetch_cycle_emits_fetch_source_done():
    from src.fetcher.main import run_fetch_cycle

    with patch("src.fetcher.main.fetch_rss_items", return_value=[]), \
         patch("src.fetcher.main.fetch_hn_items", return_value=[]), \
         patch("src.fetcher.main.fetch_reddit_items", return_value=[]), \
         patch("src.fetcher.main.fetch_x_items", return_value=[]), \
         patch("src.fetcher.main.filter_new_items", return_value=[]), \
         patch("src.fetcher.main.get_session") as mock_session, \
         patch("src.fetcher.main.settings") as mock_settings:

        mock_settings.fetcher_max_items_per_cycle = 10
        mock_settings.raw_items_queue_url = "http://q"
        mock_session.return_value = MagicMock()

        with structlog.testing.capture_logs() as cap_logs:
            run_fetch_cycle()

    source_events = [l for l in cap_logs if l.get("event") == "fetch_source_done"]
    sources = {e["source"] for e in source_events}
    assert sources == {"rss", "hackernews", "reddit", "x"}
