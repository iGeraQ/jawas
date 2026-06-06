import json
import time
import structlog
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import Draft, RawItem
from src.shared.queue import delete_message, receive_messages
from src.enricher.content_extractor import extract_content
from src.enricher.scorer import score_relevance
from src.enricher.synthesizer import generate_drafts
from src.enricher.url_resolver import resolve_url

NETWORKS = ["x"]


def process_message(body: dict) -> None:
    """Process a single SQS message: resolve URL, extract content, score, and synthesize drafts."""
    item_id = body["item_id"]
    with structlog.contextvars.bound_contextvars(item_id=item_id):
        logger.info("enricher_processing")
        session = get_session()
        try:
            item = session.get(RawItem, item_id)
            if not item:
                logger.warning("item_not_found")
                return

            url = resolve_url(item.url)
            content = extract_content(url)
            score = score_relevance(item.title, content)
            item.relevance_score = score

            if score < settings.relevance_threshold:
                item.status = "discarded"
                session.commit()
                logger.info("item_discarded", score=score)
                return

            drafts = generate_drafts(
                title=item.title,
                content=content,
                source_url=url,
                raw_content=item.raw_content or "",
                networks=NETWORKS,
            )
            item.status = "enriched"

            for network, draft_content in drafts.items():
                draft = Draft(raw_item_id=item.id, network=network, content=draft_content)
                session.add(draft)

            session.commit()
            logger.info("enricher_done", drafts_created=len(drafts))
        except Exception as e:
            session.rollback()
            logger.error("enricher_failed", error=str(e), exc_info=True)
            raise
        finally:
            session.close()


def run() -> None:
    """Main SQS consumer loop: poll raw-items-queue and process each message."""
    setup_logging()
    logger.info("enricher_started")
    while True:
        messages = receive_messages(settings.raw_items_queue_url)
        for msg in messages:
            try:
                process_message(json.loads(msg["Body"]))
                delete_message(settings.raw_items_queue_url, msg["ReceiptHandle"])
            except Exception as e:
                logger.error("message_failed", error=str(e), exc_info=True)
        if not messages:
            time.sleep(5)


if __name__ == "__main__":
    run()
