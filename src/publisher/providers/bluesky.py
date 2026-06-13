from atproto import Client, models

from src.publisher.base import PublishResult, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.logging import logger
from src.shared.rate_limit import TokenBucket


@register_publisher("bluesky")
class BlueskyProvider(SocialNetworkProvider):
    _bucket = TokenBucket(rate=300, per=3600.0)

    def __init__(self):
        self._client = Client()
        self._client.login(settings.bluesky_handle, settings.bluesky_app_password)
        self._handle = settings.bluesky_handle

    def publish(self, content: str) -> PublishResult:
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not parts:
            raise ValueError("Empty content")
        self._bucket.acquire()

        root_ref = None
        parent_ref = None
        first_uri = None

        for part in parts:
            if len(part) > 300:
                logger.warning("bluesky_truncated", original_len=len(part))
            reply_to = (
                models.AppBskyFeedPost.ReplyRef(
                    root=models.create_strong_ref(root_ref),
                    parent=models.create_strong_ref(parent_ref),
                )
                if root_ref
                else None
            )
            response = self._client.send_post(text=part[:300], reply_to=reply_to)
            if root_ref is None:
                root_ref = response
                first_uri = response.uri
            parent_ref = response

        rkey = first_uri.split("/")[-1]
        url = f"https://bsky.app/profile/{self._handle}/post/{rkey}"
        logger.info("bluesky_published", uri=first_uri)
        return PublishResult(post_id=first_uri, url=url, post_count=len(parts))
