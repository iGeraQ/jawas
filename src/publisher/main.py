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
from src.publisher.base import RateLimitExceeded, _REGISTRY, get_provider
import src.publisher.providers.x  # noqa: F401
import src.publisher.providers.bluesky  # noqa: F401
import src.publisher.providers.linkedin  # noqa: F401
import src.publisher.providers.facebook  # noqa: F401


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

            logger.info("publish_attempt", network=provider_name, draft_id=draft_id)
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
            from src.shared.metrics import publish_success_total, messages_processed_total
            publish_success_total.labels(network=provider_name).inc()
            messages_processed_total.labels(service=f"publisher-{provider_name}").inc()
        except RateLimitExceeded:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            logger.error("publish_failed", error=str(e), exc_info=True)
            from src.shared.metrics import publish_failure_total, messages_failed_total
            publish_failure_total.labels(network=provider_name, reason=type(e).__name__).inc()
            messages_failed_total.labels(service=f"publisher-{provider_name}").inc()
            raise
        finally:
            session.close()


def run(provider_name: str) -> None:
    setup_logging(f"publisher-{provider_name}")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    if provider_name not in _REGISTRY:
        logger.error("unknown_provider", provider=provider_name)
        sys.exit(1)
    logger.info("publisher_started", provider=provider_name)
    while True:
        try:
            messages = receive_messages(settings.approved_drafts_queue_url)
        except Exception as e:
            # ponytail: survive transient broker errors; retry next loop instead of crashing.
            logger.error("receive_failed", error=str(e), exc_info=True)
            time.sleep(5)
            continue
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
