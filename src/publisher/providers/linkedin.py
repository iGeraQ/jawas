import re

import httpx

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket

_URL_RE = re.compile(r"https?://\S+")


def _extract_link(content: str) -> tuple[str, str | None]:
    """Pull the source URL out of the post body for an ARTICLE card.

    The synthesizer puts the URL in the last paragraph (e.g. "Te dejo el
    artículo: https://..."). We drop the whole line holding it so no orphan
    lead-in is left in the commentary. Returns (body, url-or-None).

    ponytail: drops the entire line containing the URL, assuming the prompt
    keeps it in its own trailing paragraph. If a synthesizer ever inlines the
    URL mid-sentence, pass raw_item.url through the SQS message instead.
    """
    text = content.strip()
    matches = _URL_RE.findall(text)
    if not matches:
        return text, None
    url = matches[-1].rstrip(".,);")
    body = "\n".join(line for line in text.splitlines() if url not in line).strip()
    return body, url


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

        text, link = _extract_link(content)
        if len(text) > 3000:
            logger.warning("linkedin_truncated", original_len=len(text))
            text = text[:3000]

        share_content: dict = {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "NONE",
        }
        if link:
            # Send the source as an ARTICLE so LinkedIn renders a link card
            # (preview image + title) instead of a raw URL in the body.
            share_content["shareMediaCategory"] = "ARTICLE"
            share_content["media"] = [{"status": "READY", "originalUrl": link}]

        payload = {
            "author": settings.linkedin_author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
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
        logger.info("linkedin_published", urn=post_urn, article_card=bool(link))
        return PublishResult(post_id=post_urn, url=url, post_count=1)
