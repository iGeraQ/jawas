import asyncio
import hashlib
from playwright.async_api import async_playwright
from src.shared.config import settings
from src.shared.logging import logger


async def _scrape_profile(page, username: str) -> list[dict]:
    items = []
    try:
        await page.goto(f"https://x.com/{username}", wait_until="networkidle", timeout=30000)
        tweets = await page.query_selector_all('[data-testid="tweet"]')
        for tweet in tweets[:10]:
            text_el = await tweet.query_selector('[data-testid="tweetText"]')
            link_el = await tweet.query_selector('a[href*="/status/"]')
            if not text_el or not link_el:
                continue
            text = await text_el.inner_text()
            href = await link_el.get_attribute("href")
            url = f"https://x.com{href}" if href.startswith("/") else href
            items.append({
                "external_id": hashlib.sha256(f"x:{url}".encode()).hexdigest()[:32],
                "source": "x_scrape",
                "url": url,
                "title": text[:100],
                "raw_content": text,
            })
    except Exception as e:
        logger.warning("x_scrape_profile_failed", username=username, error=str(e))
    return items


def fetch_x_items() -> list[dict]:
    if not settings.x_profiles:
        return []

    async def run():
        all_items = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            for username in settings.x_profiles:
                items = await _scrape_profile(page, username)
                all_items.extend(items)
                logger.info("x_profile_scraped", username=username, count=len(items))
            await browser.close()
        return all_items

    return asyncio.run(run())
