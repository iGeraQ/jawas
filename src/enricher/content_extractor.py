import time
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt
from src.shared.config import settings
from src.shared.logging import logger


@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(3))
def extract_content(url: str) -> str:
    """Fetch article content via Jina AI reader API with retry logic."""
    start = time.perf_counter()
    response = httpx.get(
        f"https://r.jina.ai/{url}",
        headers={"Authorization": f"Bearer {settings.jina_api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    elapsed = time.perf_counter() - start
    duration_ms = round(elapsed * 1000, 2)
    from src.shared.metrics import http_request_duration_seconds
    http_request_duration_seconds.labels(target="jina").observe(elapsed)
    logger.info("content_extracted", url=url, chars=len(response.text), duration_ms=duration_ms)
    return response.text
