import tweepy
from tenacity import retry, stop_after_attempt, wait_exponential

from src.publisher.base import SocialNetworkProvider
from src.shared.config import settings
from src.shared.logging import logger


class XProvider(SocialNetworkProvider):
    def __init__(self):
        self._client = tweepy.Client(
            consumer_key=settings.x_api_key,
            consumer_secret=settings.x_api_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    @retry(wait=wait_exponential(multiplier=1, min=4, max=120), stop=stop_after_attempt(3))
    def publish(self, content: str) -> str:
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not parts:
            raise ValueError("Empty content")

        first_id = None
        reply_to = None
        for part in parts:
            kwargs: dict = {"text": part[:280]}
            if reply_to:
                kwargs["in_reply_to_tweet_id"] = reply_to
            resp = self._client.create_tweet(**kwargs)
            tweet_id = resp.data["id"]
            first_id = first_id or tweet_id
            reply_to = tweet_id
            logger.info("tweet_posted", tweet_id=tweet_id)

        return first_id
