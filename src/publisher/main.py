import json
import sys
import time

import structlog
from sqlalchemy import select

from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft, PublishedPost
from src.shared.queue import delete_message, receive_messages
from src.publisher.base import RateLimitExceeded, get_provider
import src.publisher.providers.x  # noqa: F401
import src.publisher.providers.bluesky  # noqa: F401


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

            existing = session.execute(
                select(PublishedPost).where(PublishedPost.draft_id == draft.id)
            ).scalar_one_or_none()
            if existing:
                logger.info("already_published", draft_id=draft_id, post_id=existing.network_post_id)
                return

            content = body.get("content") or draft.edited_content or draft.content
            provider = get_provider(provider_name)
            result = provider.publish(content)

            draft.status = "published"
            session.add(PublishedPost(
                draft_id=draft.id,
                network=provider_name,
                network_post_id=result.post_id,
                post_count=result.post_count,
                url=result.url,
            ))
            session.commit()
            logger.info("post_published", network=provider_name, post_id=result.post_id)
        except RateLimitExceeded:
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
    logger.info("publisher_started", provider=provider_name)
    while True:
        messages = receive_messages(settings.approved_drafts_queue_url)
        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                if body.get("network") == provider_name:
                    process_message(body, provider_name)
                    delete_message(settings.approved_drafts_queue_url, msg["ReceiptHandle"])
            except RateLimitExceeded as e:
                logger.warning("rate_limit_exceeded", wait_seconds=e.wait_seconds, network=provider_name)
                time.sleep(e.wait_seconds)
            except Exception as e:
                logger.error("publisher_message_failed", error=str(e), exc_info=True)
        if not messages:
            time.sleep(5)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "x")
