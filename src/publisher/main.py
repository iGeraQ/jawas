import json
import sys
import time
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select

from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft, PublishedPost
from src.shared.queue import delete_message, receive_messages
from src.publisher.providers.x import DailyLimitReached, XProvider

PROVIDERS = {"x": XProvider}


def process_message(body: dict, provider_name: str) -> None:
    draft_id = body.get("draft_id")
    if not draft_id:
        logger.error("malformed_publisher_message", body=str(body))
        return
    with structlog.contextvars.bound_contextvars(draft_id=draft_id):
        session = get_session()
        try:
            draft = session.get(Draft, draft_id)
            if not draft:
                logger.warning("draft_not_found", draft_id=draft_id)
                return
            if draft.network != provider_name:
                logger.warning(
                    "draft_wrong_network",
                    draft_id=draft_id,
                    expected=provider_name,
                    got=draft.network,
                )
                return

            # Idempotency: skip if already published
            existing = session.execute(
                select(PublishedPost).where(PublishedPost.draft_id == draft.id)
            ).scalar_one_or_none()
            if existing:
                logger.info(
                    "already_published",
                    draft_id=draft_id,
                    post_id=existing.network_post_id,
                )
                return

            content = body.get("content") or draft.edited_content or draft.content

            # Proactive daily limit check (X free tier: 17 tweets/24h)
            if provider_name == "x":
                tweet_count = len([p.strip() for p in content.split("\n\n") if p.strip()])  # must match XProvider.publish() splitting
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                used = session.scalar(
                    select(func.coalesce(func.sum(PublishedPost.tweet_count), 0))
                    .where(PublishedPost.network == "x")
                    .where(PublishedPost.published_at >= cutoff)
                ) or 0
                if used + tweet_count > settings.x_tweets_per_day:
                    raise DailyLimitReached(used=int(used), limit=settings.x_tweets_per_day)
            else:
                tweet_count = 1

            provider = PROVIDERS[provider_name]()
            post_id = provider.publish(content)
            draft.status = "published"
            session.add(PublishedPost(
                draft_id=draft.id,
                network=provider_name,
                network_post_id=post_id,
                tweet_count=tweet_count,
                url=f"https://x.com/i/web/status/{post_id}" if provider_name == "x" else None,
            ))
            session.commit()
            logger.info("post_published", network=provider_name, post_id=post_id)
        except DailyLimitReached:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error("publish_failed", error=str(e), exc_info=True)
            raise
        finally:
            session.close()


def run(provider_name: str) -> None:
    setup_logging()
    if provider_name not in PROVIDERS:
        logger.error("unknown_provider", provider=provider_name)
        sys.exit(1)
    logger.info("publisher_started", provider=provider_name)
    while True:
        messages = receive_messages(settings.approved_drafts_queue_url)
        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                if body.get("network") == provider_name:
                    process_message(body, provider_name)
                    delete_message(settings.approved_drafts_queue_url, msg["ReceiptHandle"])
                # If network doesn't match, leave message for the correct worker.
            except DailyLimitReached as e:
                # Compute wait until the oldest in-window tweet falls out of the 24h window
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                reset_session = get_session()
                try:
                    oldest = reset_session.scalar(
                        select(func.min(PublishedPost.published_at))
                        .where(PublishedPost.network == "x")
                        .where(PublishedPost.published_at >= cutoff)
                    )
                finally:
                    reset_session.close()
                reset_at = oldest + timedelta(hours=24) if oldest else datetime.now(timezone.utc)
                wait = max(0, (reset_at - datetime.now(timezone.utc)).total_seconds()) + 60
                logger.warning("x_daily_limit_reached", used=e.used, limit=e.limit, wait_seconds=int(wait))
                time.sleep(wait)
                # SQS message is NOT deleted — redelivered after visibility timeout
            except Exception as e:
                logger.error("publisher_message_failed", error=str(e), exc_info=True)
        if not messages:
            time.sleep(5)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "x")
