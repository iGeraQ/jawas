import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from src.shared.config import settings
from src.shared.db import get_session
from src.shared.logging import setup_logging, logger
from src.shared.models import RawItem
from src.shared.queue import send_message
from src.fetcher.deduplicator import filter_new_items
from src.fetcher.sources.hackernews import fetch_hn_items
from src.fetcher.sources.reddit import fetch_reddit_items
from src.fetcher.sources.rss import fetch_rss_items
from src.fetcher.sources.x_scraper import fetch_x_items


def run_fetch_cycle() -> None:
    with structlog.contextvars.bound_contextvars(cycle="fetch"):
        logger.info("fetch_cycle_start")
        all_items = (
            fetch_rss_items()
            + fetch_hn_items()
            + fetch_reddit_items()
            + fetch_x_items()
        )
        logger.info("fetch_cycle_collected", total=len(all_items))

        session = get_session()
        try:
            new_items = filter_new_items(session, all_items)
            for item in new_items:
                db_item = RawItem(**item)
                session.add(db_item)
                session.flush()
                send_message(settings.raw_items_queue_url, {
                    "item_id": str(db_item.id),
                    "url": item["url"],
                    "title": item["title"],
                    "source": item["source"],
                    "raw_content": item.get("raw_content", ""),
                })
            session.commit()
            logger.info("fetch_cycle_done", enqueued=len(new_items))
        except Exception as e:
            session.rollback()
            logger.error("fetch_cycle_failed", error=str(e))
        finally:
            session.close()


if __name__ == "__main__":
    setup_logging()
    scheduler = BlockingScheduler()
    scheduler.add_job(run_fetch_cycle, "interval", hours=settings.fetch_interval_hours)
    run_fetch_cycle()
    scheduler.start()
