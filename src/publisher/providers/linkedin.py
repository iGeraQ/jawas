import httpx

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket


@register_publisher("linkedin")
class LinkedInProvider(SocialNetworkProvider):
    _API_URL = "https://api.linkedin.com/v2/ugcPosts"
    _bucket = TokenBucket(rate=80, per=86400.0)

    def publish(self, content: str) -> PublishResult:
        if not content.strip():
            raise ValueError("Empty content")
        if not settings.linkedin_author_urn:
            raise ValueError("LINKEDIN_AUTHOR_URN is not configured")
        self._bucket.acquire()

        text = content.strip()
        if len(text) > 3000:
            logger.warning("linkedin_truncated", original_len=len(text))
            text = text[:3000]

        payload = {
            "author": settings.linkedin_author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        headers = {
            "Authorization": f"Bearer {settings.linkedin_access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        resp = httpx.post(self._API_URL, json=payload, headers=headers)
        if not resp.is_success:
            logger.error(
                "linkedin_api_error",
                status=resp.status_code,
                body=resp.text,
                author_urn=settings.linkedin_author_urn,
            )
            raise ValueError(
                f"LinkedIn API error {resp.status_code}: {resp.text}"
            )

        post_urn = resp.headers.get("x-restli-id", "")
        if not post_urn:
            raise ValueError("LinkedIn API did not return x-restli-id header")
        url = f"https://www.linkedin.com/feed/update/{post_urn}/"
        logger.info("linkedin_published", urn=post_urn)
        return PublishResult(post_id=post_urn, url=url, post_count=1)
