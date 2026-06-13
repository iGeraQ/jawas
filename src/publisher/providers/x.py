from datetime import datetime, timedelta, timezone

import tweepy
from sqlalchemy import func, select
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.publisher.base import PublishResult, RateLimitExceeded, SocialNetworkProvider, register_publisher
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import logger
from src.shared.models import PublishedPost


@register_publisher("x")
class XProvider(SocialNetworkProvider):
    def __init__(self):
        self._client = tweepy.Client(
            consumer_key=settings.x_consumer_key,
            consumer_secret=settings.x_consumer_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    def _check_daily_limit(self, post_count: int) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        session = get_session()
        try:
            used = session.scalar(
                select(func.coalesce(func.sum(PublishedPost.post_count), 0))
                .where(PublishedPost.network == "x")
                .where(PublishedPost.published_at >= cutoff)
            ) or 0
            if used + post_count > settings.x_tweets_per_day:
                oldest = session.scalar(
                    select(func.min(PublishedPost.published_at))
                    .where(PublishedPost.network == "x")
                    .where(PublishedPost.published_at >= cutoff)
                )
                reset_at = oldest + timedelta(hours=24) if oldest else datetime.now(timezone.utc)
                wait = max(0, (reset_at - datetime.now(timezone.utc)).total_seconds()) + 60
                raise RateLimitExceeded(wait_seconds=int(wait))
        finally:
            session.close()

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
            raise

    def publish(self, content: str) -> PublishResult:
        parts = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not parts:
            raise ValueError("Empty content")

        self._check_daily_limit(len(parts))

        first_id = None
        reply_to = None
        for part in parts:
            if len(part) > 280:
                logger.warning("tweet_truncated", original_len=len(part))
            tweet_id = self._post_tweet(part[:280], reply_to)
            first_id = first_id or tweet_id
            reply_to = tweet_id

        return PublishResult(
            post_id=first_id,
            url=f"https://x.com/i/web/status/{first_id}",
            post_count=len(parts),
        )
