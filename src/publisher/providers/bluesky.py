import re

from atproto import Client, models

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket

_URL_RE = re.compile(r'https?://\S+')


def _build_facets(text: str) -> list:
    facets = []
    for match in _URL_RE.finditer(text):
        url = re.sub(r'[.,;:!?)\]]+$', '', match.group())
        if not url:
            continue
        # Byte offsets are required by the AT Protocol; Spanish text has multi-byte chars.
        byte_start = len(text[:match.start()].encode('utf-8'))
        byte_end = byte_start + len(url.encode('utf-8'))
        facets.append(
            models.AppBskyRichtextFacet.Main(
                features=[models.AppBskyRichtextFacet.Link(uri=url)],
                index=models.AppBskyRichtextFacet.ByteSlice(
                    byte_start=byte_start,
                    byte_end=byte_end,
                ),
            )
        )
    return facets


@register_publisher("bluesky")
class BlueskyProvider(SocialNetworkProvider):
    _bucket = TokenBucket(rate=300, per=3600.0)

    def __init__(self):
        self._client = Client()
        self._client.login(settings.bluesky_handle, settings.bluesky_app_password)
        self._handle = settings.bluesky_handle

    def publish(self, content: str) -> PublishResult:
        if not content.strip():
            raise ValueError("Empty content")

        self._bucket.acquire()

        text = content[:300]
        if len(content) > 300:
            logger.warning("bluesky_truncated", original_len=len(content))

        facets = _build_facets(text)
        response = self._client.send_post(text=text, facets=facets or None)

        rkey = response.uri.split("/")[-1]
        url = f"https://bsky.app/profile/{self._handle}/post/{rkey}"
        logger.info("bluesky_published", uri=response.uri)
        return PublishResult(post_id=response.uri, url=url, post_count=1)
