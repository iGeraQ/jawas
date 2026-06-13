import httpx

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket


@register_publisher("facebook")
class FacebookProvider(SocialNetworkProvider):
    _API_BASE = "https://graph.facebook.com/v19.0"
    _bucket = TokenBucket(rate=150, per=3600.0)

    def publish(self, content: str) -> PublishResult:
        if not content.strip():
            raise ValueError("Empty content")
        self._bucket.acquire()

        page_id = settings.facebook_page_id
        resp = httpx.post(
            f"{self._API_BASE}/{page_id}/feed",
            data={
                "message": content.strip(),
                "access_token": settings.facebook_page_access_token,
            },
        )
        resp.raise_for_status()

        full_id = resp.json()["id"]  # "{page_id}_{object_id}"
        object_id = full_id.split("_")[-1]
        url = f"https://www.facebook.com/{page_id}/posts/{object_id}"
        logger.info("facebook_published", post_id=full_id)
        return PublishResult(post_id=full_id, url=url, post_count=1)
