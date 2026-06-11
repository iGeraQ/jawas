import tweepy
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.publisher.base import SocialNetworkProvider
from src.shared.config import settings
from src.shared.logging import logger


class DailyLimitReached(Exception):
    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit
        super().__init__(f"X daily tweet limit reached ({used}/{limit})")


class XProvider(SocialNetworkProvider):
    def __init__(self):
        self._client = tweepy.Client(
            consumer_key=settings.x_consumer_key,
            consumer_secret=settings.x_consumer_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    @retry(
        retry=retry_if_exception_type(tweepy.errors.TwitterServerError),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _post_tweet(self, text: str, reply_to_id: str | None = None) -> str:
        try:
            kwargs: dict = {"text": text}
            if reply_to_id:
                kwargs["in_reply_to_tweet_id"] = reply_to_id
            resp = self._client.create_tweet(**kwargs)
            tweet_id = resp.data.get("id") if resp.data else None
            if not tweet_id:
                raise ValueError(f"Unexpected tweepy response: {resp}")
            logger.info("tweet_posted", tweet_id=tweet_id)
            return tweet_id
        except tweepy.errors.TooManyRequests as e:
            reset_ts = int(e.response.headers.get("x-rate-limit-reset", 0))
            logger.warning("x_rate_limit_429", reset_at=reset_ts)
            raise  # tenacity does not catch TooManyRequests — propagates immediately

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
