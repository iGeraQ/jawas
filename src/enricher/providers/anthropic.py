import anthropic

from src.enricher.providers.base import AIProvider, AIProviderName, register
from src.shared.config import settings
from src.shared.logging import logger

_SCORE_PROMPT = """Rate this AI news item's relevance for a professional AI audience (0-10).
Reply with a single integer only. No explanation.

Title: {title}
Content: {preview}

Guide: 0-3=off-topic, 4-6=tangential, 7-8=relevant+technical, 9-10=major breakthrough"""

_SYNTHESIS_PROMPTS = {
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


@register(AIProviderName.ANTHROPIC)
class AnthropicProvider(AIProvider):
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def score(self, title: str, content: str) -> int:
        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": _SCORE_PROMPT.format(
                    title=title, preview=content[:500]
                )}],
            )
            score = max(0, min(10, int(response.content[0].text.strip())))
            logger.info("item_scored", provider="anthropic", title=title[:50], score=score)
            return score
        except Exception as e:
            logger.warning("scoring_failed", provider="anthropic", title=title[:50], error=str(e))
            return 0

    def synthesize(
        self,
        title: str,
        content: str,
        source_url: str,
        raw_content: str,
        networks: list[str],
    ) -> dict[str, str]:
        drafts = {}
        for network in networks:
            if network not in _SYNTHESIS_PROMPTS:
                logger.warning("unknown_network", network=network)
                continue
            try:
                response = self._client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=600,
                    messages=[{"role": "user", "content": _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    )}],
                )
                drafts[network] = response.content[0].text.strip()
                logger.info("draft_generated", provider="anthropic", network=network, title=title[:50])
            except Exception as e:
                logger.error("synthesis_failed", provider="anthropic", network=network, error=str(e))
        return drafts
