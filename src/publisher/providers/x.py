import tweepy
from tenacity import retry, stop_after_attempt, wait_exponential

from src.publisher.base import SocialNetworkProvider
from src.shared.config import settings
from src.shared.logging import logger


class XProvider(SocialNetworkProvider):
    def __init__(self):
        self._client = tweepy.Client(
            consumer_key=settings.x_consumer_key,
            consumer_secret=settings.x_consumer_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    @retry(wait=wait_exponential(multiplier=1, min=4, max=120), stop=stop_after_attempt(3))
    def _post_tweet(self, text: str, reply_to_id: str | None = None) -> str:
        """Post a single tweet, retrying on transient failures.

        Keeping retry here (not on publish()) prevents duplicate tweets when a
        mid-thread tweet fails and tenacity retries from the beginning.
        """
        kwargs: dict = {"text": text}
        if reply_to_id:
            kwargs["in_reply_to_tweet_id"] = reply_to_id
        resp = self._client.create_tweet(**kwargs)
        tweet_id = resp.data.get("id") if resp.data else None
        if not tweet_id:
            raise ValueError(f"Unexpected tweepy response: {resp}")
        logger.info("tweet_posted", tweet_id=tweet_id)
        return tweet_id

    def publish(self, content: str) -> str:
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not parts:
            raise ValueError("Empty content")

        first_id = None
        reply_to = None
        for part in parts:
            if len(part) > 280:
                logger.warning("tweet_truncated", original_len=len(part))
            tweet_id = self._post_tweet(part[:280], reply_to)
            first_id = first_id or tweet_id
            reply_to = tweet_id

        return first_id
