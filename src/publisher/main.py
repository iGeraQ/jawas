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
from src.publisher.providers.x import XProvider

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
                return  # caller will delete the message
            if draft.network != provider_name:
                logger.warning(
                    "draft_wrong_network",
                    draft_id=draft_id,
                    expected=provider_name,
                    got=draft.network,
                )
                return  # caller will delete the message

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

            content = body.get("content") or draft.content
            provider = PROVIDERS[provider_name]()
            post_id = provider.publish(content)
            draft.status = "published"
            session.add(PublishedPost(
                draft_id=draft.id,
                network=provider_name,
                network_post_id=post_id,
                url=f"https://x.com/i/web/status/{post_id}" if provider_name == "x" else None,
            ))
            session.commit()
            logger.info("post_published", network=provider_name, post_id=post_id)
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
                    # Always delete after process_message returns (processed or
                    # permanently unprocessable). Only skip delete on exception
                    # so transient failures stay in the queue for retry / DLQ.
                    delete_message(settings.approved_drafts_queue_url, msg["ReceiptHandle"])
                # If network doesn't match, leave message for the correct worker.
            except Exception as e:
                logger.error("publisher_message_failed", error=str(e), exc_info=True)
        if not messages:
            time.sleep(5)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "x")
