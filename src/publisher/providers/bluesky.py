import re

from atproto import Client, models

from src.publisher.base import (
    PublishResult,
    SocialNetworkProvider,
    register_publisher,
    split_into_thread,
)
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket

_URL_RE = re.compile(r'https?://\S+')
_POST_LIMIT = 300  # Bluesky caps posts at 300 graphemes; code points are a safe upper bound.


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

        chunks = split_into_thread(content, _POST_LIMIT)

        self._bucket.acquire()
        root = self._client.send_post(
            text=chunks[0], facets=_build_facets(chunks[0]) or None
        )

        if len(chunks) > 1:
            root_ref = models.create_strong_ref(root)
            parent_ref = root_ref
            for chunk in chunks[1:]:
                self._bucket.acquire()
                resp = self._client.send_post(
                    text=chunk,
                    facets=_build_facets(chunk) or None,
                    reply_to=models.AppBskyFeedPost.ReplyRef(root=root_ref, parent=parent_ref),
                )
                parent_ref = models.create_strong_ref(resp)
            logger.info("bluesky_thread_posted", posts=len(chunks), root_uri=root.uri)

        rkey = root.uri.split("/")[-1]
        url = f"https://bsky.app/profile/{self._handle}/post/{rkey}"
        logger.info("bluesky_published", uri=root.uri, posts=len(chunks))
        return PublishResult(post_id=root.uri, url=url, post_count=len(chunks))
