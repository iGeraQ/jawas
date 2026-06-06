from unittest.mock import patch, MagicMock
import httpx
from src.enricher.url_resolver import resolve_url

def test_resolve_url_follows_redirects():
    with patch("httpx.head") as mock_head:
        mock_head.return_value = MagicMock(url=httpx.URL("https://final-url.com/article"))
        result = resolve_url("https://t.co/short123")
    assert result == "https://final-url.com/article"

def test_resolve_url_returns_original_on_error():
    with patch("httpx.head", side_effect=Exception("timeout")):
        result = resolve_url("https://t.co/broken")
    assert result == "https://t.co/broken"
