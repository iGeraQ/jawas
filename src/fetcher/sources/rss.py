import hashlib
import feedparser
from src.shared.logging import logger

RSS_FEEDS = [
    "https://www.anthropic.com/rss.xml",
    "https://openai.com/news/rss.xml",
    "https://deepmind.google/blog/rss/feed.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://paperswithcode.com/rss.xml",
    "https://www.deeplearning.ai/the-batch/feed/",
]


def fetch_rss_items(feeds: list[str] = RSS_FEEDS) -> list[dict]:
    items = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            before = len(items)
            for entry in feed.entries:
                link = getattr(entry, "link", "") or ""
                if not link:
                    continue
                items.append({
                    "external_id": hashlib.sha256(f"rss:{link}".encode()).hexdigest()[:32],
                    "source": "rss",
                    "url": link,
                    "title": getattr(entry, "title", "") or "",
                    "raw_content": getattr(entry, "summary", "") or "",
                })
            logger.info("rss_fetched", feed=url, count=len(items) - before)
        except Exception as e:
            logger.warning("rss_fetch_failed", feed=url, error=str(e))
    return items
