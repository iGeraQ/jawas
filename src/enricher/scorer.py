import anthropic
from src.shared.config import settings
from src.shared.logging import logger

_PROMPT = """Rate this AI news item's relevance for a professional AI audience (0-10).
Reply with a single integer only. No explanation.

Title: {title}
Content: {preview}

Guide: 0-3=off-topic, 4-6=tangential, 7-8=relevant+technical, 9-10=major breakthrough"""


def score_relevance(title: str, content: str) -> int:
    """Score how relevant an AI news item is using Claude Haiku. Returns 0-10."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": _PROMPT.format(
                title=title, preview=content[:500]
            )}],
        )
        score = int(response.content[0].text.strip())
        logger.info("item_scored", title=title[:50], score=score)
        return score
    except Exception as e:
        logger.warning("scoring_failed", title=title[:50], error=str(e))
        return 0
