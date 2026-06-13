import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.enricher.providers.base import AIProvider, AIProviderName, TokenBucket, register
from src.shared.config import settings
from src.shared.logging import logger

_SCORE_PROMPT = """Rate this AI news item's relevance for a professional AI audience (0-10).
Reply with a single integer only. No explanation.

Title: {title}
Content: {preview}

Guide: 0-3=off-topic, 4-6=tangential, 7-8=relevant+technical, 9-10=major breakthrough"""

_SYNTHESIS_PROMPTS = {
    "x": """IDIOMA: Escribe SIEMPRE en español mexicano neutro, sin importar el idioma del artículo fuente.

Eres un curador de noticias de IA. Escribe un hilo de tweets (máx. 3 tweets, 280 caracteres cada uno).

ESTILO OBLIGATORIO — imita exactamente esta voz:
- Primer tweet: primera línea en MAYÚSCULAS resumiendo el hallazgo principal. Segunda línea: métrica o resultado concreto (números reales si los hay). Resto: lista con → o numerada con 1) 2) 3), una idea por línea.
- Español mexicano neutro con tuteo: "haz", "usa", "define", "tienes", "vas a", "puedes". Nunca voseo ("hacé", "usá", "tenés").
- Párrafos cortísimos. Una idea por línea. Sin relleno.
- Paréntesis para contexto sin romper el flujo: "(solo cuentas sub-500K, las grandes son ruido)"
- Cita empresas y personas reales mencionadas en el artículo.
- Sin hashtags. Emojis: máximo 1, solo si aporta.
- Último tweet: incluye la URL fuente.

Fuente: {source_url}
Post original: {raw_content}
Título: {title}
Artículo: {content}

Escribe ÚNICAMENTE el hilo. Separa los tweets con líneas en blanco.""",

    "linkedin": """IDIOMA: Escribe SIEMPRE en español mexicano neutro, sin importar el idioma del artículo fuente.

Eres un curador de noticias de IA. Escribe un post de LinkedIn (máx. 300 palabras).

ESTILO OBLIGATORIO — imita exactamente esta voz:
- Primera línea: afirmación o dato impactante (puede ir en MAYÚSCULAS).
- Cuerpo: lista numerada 1) 2) 3) o con →, una idea por línea, sin párrafos largos.
- Español mexicano neutro con tuteo: "haz", "usa", "define", "tienes", "vas a", "puedes". Nunca voseo ("hacé", "usá", "tenés").
- Cita empresas y métricas reales del artículo.
- Agrega una conclusión o análisis propio al final (1-2 líneas).
- Sin hashtags. Sin emojis decorativos (máximo 1 si aporta).
- Último párrafo: incluye la URL fuente con "Te dejo el artículo:" o similar.

Fuente: {source_url}
Título: {title}
Artículo: {content}

Escribe ÚNICAMENTE el texto del post.""",

    "bluesky": """IDIOMA: Escribe SIEMPRE en español mexicano neutro, sin importar el idioma del artículo fuente.

Eres un curador de noticias de IA. Escribe un hilo de posts para Bluesky (máx. 3 posts, 300 caracteres cada uno).

ESTILO OBLIGATORIO — imita exactamente esta voz:
- Primer post: primera línea en MAYÚSCULAS resumiendo el hallazgo principal. Segunda línea: métrica o resultado concreto (números reales si los hay). Resto: lista con → o numerada con 1) 2) 3), una idea por línea.
- Español mexicano neutro con tuteo: "haz", "usa", "define", "tienes", "vas a", "puedes". Nunca voseo ("hacé", "usá", "tenés").
- Párrafos cortísimos. Una idea por línea. Sin relleno.
- Cita empresas y personas reales mencionadas en el artículo.
- Sin hashtags. Emojis: máximo 1, solo si aporta.
- Último post: incluye la URL fuente.

Fuente: {source_url}
Post original: {raw_content}
Título: {title}
Artículo: {content}

Escribe ÚNICAMENTE el hilo. Separa los posts con líneas en blanco.""",

    "facebook": """IDIOMA: Escribe SIEMPRE en español mexicano neutro, sin importar el idioma del artículo fuente.

Eres un curador de noticias de IA. Escribe un post de Facebook (máx. 500 palabras).

ESTILO OBLIGATORIO — imita exactamente esta voz:
- Primera línea: pregunta o afirmación impactante para captar atención.
- Cuerpo: explicación accesible con contexto suficiente, lista con → o numerada con 1) 2) 3), una idea por línea.
- Español mexicano neutro con tuteo: "haz", "usa", "define", "tienes", "vas a", "puedes". Nunca voseo ("hacé", "usá", "tenés").
- Tono conversacional pero informativo. Más contexto que en X o Bluesky.
- Cita empresas y métricas reales del artículo.
- Sin hashtags. Sin emojis decorativos (máximo 2 si aportan).
- Último párrafo: incluye la URL fuente con "Lee más aquí:" o similar.

Fuente: {source_url}
Título: {title}
Artículo: {content}

Escribe ÚNICAMENTE el texto del post.""",
}


@register(AIProviderName.ANTHROPIC)
class AnthropicProvider(AIProvider):
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._bucket = TokenBucket(rate=settings.anthropic_rpm)

    @retry(
        retry=retry_if_exception_type(anthropic.RateLimitError),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _call(self, model: str, messages: list[dict], max_tokens: int):
        self._bucket.acquire()
        return self._client.messages.create(
            model=model, messages=messages, max_tokens=max_tokens
        )

    def score(self, title: str, content: str) -> int:
        try:
            response = self._call(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": _SCORE_PROMPT.format(
                    title=title, preview=content[:500]
                )}],
                max_tokens=5,
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
                response = self._call(
                    model="claude-sonnet-4-6",
                    messages=[{"role": "user", "content": _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    )}],
                    max_tokens=600,
                )
                drafts[network] = response.content[0].text.strip()
                logger.info("draft_generated", provider="anthropic", network=network, title=title[:50])
            except Exception as e:
                logger.error("synthesis_failed", provider="anthropic", network=network, error=str(e))
        return drafts
