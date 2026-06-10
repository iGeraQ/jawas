import hashlib
import httpx
from src.shared.config import settings
from src.shared.logging import logger

HN_BASE = "https://hacker-news.firebaseio.com/v0"


def fetch_hn_items(keywords: list[str] | None = None, limit: int = 30) -> list[dict]:
    if keywords is None:
        keywords = settings.hn_keywords
    try:
        ids = httpx.get(f"{HN_BASE}/topstories.json", timeout=10).json()[:limit]
    except Exception as e:
        logger.warning("hn_fetch_failed", error=str(e))
        return []

    kw_lower = [k.lower() for k in keywords]
    items = []
    for story_id in ids[:4]:  # Limit to 4 items
        try:
            story = httpx.get(f"{HN_BASE}/item/{story_id}.json", timeout=5).json()
            if not story or story.get("type") != "story":
                continue
            title = story.get("title", "")
            if not any(kw in title.lower() for kw in kw_lower):
                continue
            url = story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            items.append({
                "external_id": hashlib.sha256(f"hn:{story_id}".encode()).hexdigest()[:32],
                "source": "hackernews",
                "url": url,
                "title": title,
                "raw_content": story.get("text", ""),
            })
        except Exception as e:
            logger.warning("hn_item_failed", item_id=story_id, error=str(e))

    logger.info("hn_fetched", count=len(items))
    return items
