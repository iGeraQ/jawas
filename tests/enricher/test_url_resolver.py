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

def test_resolve_url_logs_debug_on_success():
    import structlog.testing
    from unittest.mock import patch, MagicMock

    mock_response = MagicMock()
    mock_response.url = "https://final.example.com/page"
    mock_response.history = [MagicMock()]  # one redirect

    with patch("src.enricher.url_resolver.httpx.head", return_value=mock_response):
        with structlog.testing.capture_logs() as cap_logs:
            from src.enricher.url_resolver import resolve_url
            resolve_url("https://original.example.com")

    resolved = [l for l in cap_logs if l.get("event") == "url_resolved"]
    assert len(resolved) == 1
    assert resolved[0]["redirect_count"] == 1
    assert resolved[0]["final_url"] == "https://final.example.com/page"
