import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.fetcher.sources.x_scraper import fetch_x_items


def _make_playwright_mock():
    """Return a mock async context manager that mimics playwright's API."""
    mock_page = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.new_page.return_value = mock_page

    mock_pw_ctx = AsyncMock()
    mock_pw_ctx.chromium.launch.return_value = mock_browser

    mock_pw_cm = MagicMock()
    mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
    mock_pw_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_pw_cm


def test_scraper_sleeps_between_profiles():
    with patch("src.fetcher.sources.x_scraper.settings") as mock_settings, \
         patch("src.fetcher.sources.x_scraper.async_playwright", return_value=_make_playwright_mock()), \
         patch("src.fetcher.sources.x_scraper._scrape_profile", new_callable=AsyncMock, return_value=[]), \
         patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:

        mock_settings.x_profiles = ["user1", "user2", "user3"]
        mock_settings.x_scraper_delay_seconds = 2.0

        fetch_x_items()

    assert mock_sleep.call_count == 3
    mock_sleep.assert_called_with(2.0)
