import httpx
from src.shared.logging import logger


def resolve_url(url: str) -> str:
    """Follow redirects and return the final URL. Returns original on error."""
    try:
        response = httpx.head(url, follow_redirects=True, timeout=10)
        final = str(response.url)
        logger.debug(
            "url_resolved",
            original_url=url,
            final_url=final,
            redirect_count=len(response.history),
        )
        return final
    except Exception as e:
        logger.warning("url_resolve_failed", url=url, error=str(e))
        return url
