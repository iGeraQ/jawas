import time
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


def _fetch_with_timing(source_name: str, fetch_fn) -> list:
    """Fetch items from a source and log timing information."""
    logger.debug("fetch_source_start", source=source_name)
    start_time = time.time()
    items = fetch_fn()[:20]
    duration_ms = int((time.time() - start_time) * 1000)
    logger.info("fetch_source_done", source=source_name, count=len(items), duration_ms=duration_ms)
    return items


def run_fetch_cycle() -> None:
    with structlog.contextvars.bound_contextvars(cycle="fetch"):
        logger.info("fetch_cycle_start")
        raw = (
            _fetch_with_timing("rss", fetch_rss_items)
            + _fetch_with_timing("hackernews", fetch_hn_items)
            + _fetch_with_timing("reddit", fetch_reddit_items)
            + _fetch_with_timing("x", fetch_x_items)
        )
        logger.info("fetch_cycle_collected", total=len(raw))

        session = get_session()
        try:
            new_items = filter_new_items(session, raw)
            total_raw = len(raw)
            new_count = len(new_items)
            duplicates = total_raw - new_count
            logger.info("dedup_stats", total=total_raw, new=new_count, duplicates=duplicates)

            new_items = new_items[:settings.fetcher_max_items_per_cycle]

            from src.shared import metrics
            metrics.fetch_cycle_items_new.set(new_count)

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
                metrics.items_fetched_total.labels(source=item["source"]).inc()
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
    # next_run_time is only set after scheduler.start(); don't read it here.
    scheduler.add_job(run_fetch_cycle, "interval", hours=settings.fetch_interval_hours)
    run_fetch_cycle()
    scheduler.start()
