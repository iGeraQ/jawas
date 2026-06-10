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


def _has_content(item: dict) -> bool:
    return len((item.get("raw_content") or "").strip()) >= 20


def run_fetch_cycle() -> None:
    with structlog.contextvars.bound_contextvars(cycle="fetch"):
        logger.info("fetch_cycle_start")
        raw = (
            fetch_rss_items()[:1]
            + fetch_hn_items()[:1]
            + fetch_reddit_items()[:1]
            + fetch_x_items()[:1]
        )
        all_items = [i for i in raw if _has_content(i)]
        dropped = len(raw) - len(all_items)
        if dropped:
            logger.info("fetch_cycle_no_content_dropped", dropped=dropped)

        logger.info("fetch_cycle_collected", total=len(all_items))

        session = get_session()
        try:
            new_items = filter_new_items(session, all_items)
            new_items = new_items[:settings.fetcher_max_items_per_cycle]
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
            logger.error("fetch_cycle_failed", error=str(e), exc_info=True)
        finally:
            session.close()


if __name__ == "__main__":
    setup_logging()
    scheduler = BlockingScheduler()
    scheduler.add_job(run_fetch_cycle, "interval", hours=settings.fetch_interval_hours)
    run_fetch_cycle()
    scheduler.start()
