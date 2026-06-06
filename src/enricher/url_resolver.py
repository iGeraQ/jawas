import httpx
from src.shared.logging import logger


def resolve_url(url: str) -> str:
    """Follow redirects and return the final URL. Returns original on error."""
    try:
        response = httpx.head(url, follow_redirects=True, timeout=10)
        return str(response.url)
    except Exception as e:
        logger.warning("url_resolve_failed", url=url, error=str(e))
        return url
