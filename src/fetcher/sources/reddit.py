import hashlib
import praw
from src.shared.config import settings
from src.shared.logging import logger


def fetch_reddit_items() -> list[dict]:
    if not settings.reddit_client_id:
        logger.info("reddit_skipped", reason="no credentials configured")
        return []
    try:
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        items = []
        for sub in settings.reddit_subreddits:
            for post in reddit.subreddit(sub).hot(limit=25)[:4]:  # Limit to 4 items per subreddit
                items.append({
                    "external_id": hashlib.sha256(f"reddit:{post.id}".encode()).hexdigest()[:32],
                    "source": "reddit",
                    "url": f"https://reddit.com{post.permalink}",
                    "title": post.title,
                    "raw_content": post.selftext,
                })
        logger.info("reddit_fetched", count=len(items))
        return items
    except Exception as e:
        logger.warning("reddit_fetch_failed", error=str(e))
        return []
