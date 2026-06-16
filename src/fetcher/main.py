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
        raw = (
            fetch_rss_items()[:20]
            + fetch_hn_items()[:20]
            + fetch_reddit_items()[:20]
            + fetch_x_items()[:20]
        )
        logger.info("fetch_cycle_collected", total=len(raw))

        session = get_session()
        try:
            new_items = filter_new_items(session, raw)
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
    setup_logging("fetcher")
    from src.shared.logging import log_startup_config
    from src.shared.metrics import start_metrics_server
    log_startup_config()
    start_metrics_server(settings.metrics_port)
    scheduler = BlockingScheduler()
    job = scheduler.add_job(run_fetch_cycle, "interval", hours=settings.fetch_interval_hours)
    logger.debug("scheduler_next_run", next_run_at=str(job.next_run_time))
    run_fetch_cycle()
    scheduler.start()
