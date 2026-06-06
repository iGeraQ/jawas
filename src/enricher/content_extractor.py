import httpx
from tenacity import retry, wait_exponential, stop_after_attempt
from src.shared.config import settings
from src.shared.logging import logger


@retry(wait=wait_exponential(multiplier=1, min=4, max=60), stop=stop_after_attempt(3))
def extract_content(url: str) -> str:
    """Fetch article content via Jina AI reader API with retry logic."""
    response = httpx.get(
        f"https://r.jina.ai/{url}",
        headers={"Authorization": f"Bearer {settings.jina_api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    logger.info("content_extracted", url=url, chars=len(response.text))
    return response.text
