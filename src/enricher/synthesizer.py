import anthropic
from src.shared.config import settings
from src.shared.logging import logger

_PROMPTS = {
    "x": """You are a professional AI curator. Write a tweet thread (max 3 tweets, 280 chars each).
Be informative and engaging. Include the source URL in the last tweet.

Source: {source_url}
Original post: {raw_content}
Title: {title}
Article: {content}

Write ONLY the thread. Separate tweets with blank lines.""",

    "linkedin": """You are a professional AI curator. Write a LinkedIn post (max 300 words).
Be professional and insightful. Add your own analysis. Include the source URL.

Source: {source_url}
Title: {title}
Article: {content}

Write ONLY the post text.""",
}

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def generate_drafts(
    title: str,
    content: str,
    source_url: str,
    raw_content: str,
    networks: list[str] | None = None,
) -> dict[str, str]:
    if networks is None:
        networks = ["x"]
    drafts = {}
    for network in networks:
        if network not in _PROMPTS:
            logger.warning("unknown_network", network=network)
            continue
        try:
            response = _client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                messages=[{"role": "user", "content": _PROMPTS[network].format(
                    title=title,
                    content=content[:3000],
                    source_url=source_url,
                    raw_content=raw_content[:500],
                )}],
            )
            drafts[network] = response.content[0].text.strip()
            logger.info("draft_generated", network=network, title=title[:50])
        except Exception as e:
            logger.error("synthesis_failed", network=network, error=str(e), exc_info=True)
    return drafts
