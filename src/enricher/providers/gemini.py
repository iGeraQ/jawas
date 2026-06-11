import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
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
    "x": """Eres un curador de noticias de IA. Escribe un hilo de tweets (máx. 3 tweets, 280 caracteres cada uno).

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

    "linkedin": """Eres un curador de noticias de IA. Escribe un post de LinkedIn (máx. 300 palabras).

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
}


@register(AIProviderName.GEMINI)
class GeminiProvider(AIProvider):
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        self._flash = genai.GenerativeModel("gemini-2.0-flash")
        self._pro = genai.GenerativeModel("gemini-2.5-pro")
        self._bucket = TokenBucket(rate=settings.gemini_rpm)

    @retry(
        retry=retry_if_exception_type(ResourceExhausted),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _call(self, model, prompt: str):
        self._bucket.acquire()
        return model.generate_content(prompt)

    def score(self, title: str, content: str) -> int:
        try:
            response = self._call(
                self._flash,
                _SCORE_PROMPT.format(title=title, preview=content[:500]),
            )
            score = max(0, min(10, int(response.text.strip())))
            logger.info("item_scored", provider="gemini", title=title[:50], score=score)
            return score
        except Exception as e:
            logger.warning("scoring_failed", provider="gemini", title=title[:50], error=str(e))
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
                    self._pro,
                    _SYNTHESIS_PROMPTS[network].format(
                        title=title,
                        content=content[:3000],
                        source_url=source_url,
                        raw_content=raw_content[:500],
                    ),
                )
                drafts[network] = response.text.strip()
                logger.info("draft_generated", provider="gemini", network=network, title=title[:50])
            except Exception as e:
                logger.error("synthesis_failed", provider="gemini", network=network, error=str(e))
        return drafts
