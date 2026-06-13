from abc import ABC, abstractmethod
from enum import Enum

from src.shared.rate_limit import TokenBucket  # re-exported for backward compat


class AIProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI = "openai"


class AIProvider(ABC):
    @abstractmethod
    def score(self, title: str, content: str) -> int:
        """Return relevance score 0-10. Returns 0 on failure."""
        ...

    @abstractmethod
    def synthesize(
        self,
        title: str,
        content: str,
        source_url: str,
        raw_content: str,
        networks: list[str],
    ) -> dict[str, str]:
        """Return {network: draft_text} for each requested network. Skips failures."""
        ...


_REGISTRY: dict[AIProviderName, type[AIProvider]] = {}


def register(name: AIProviderName):
    def decorator(cls: type[AIProvider]) -> type[AIProvider]:
        _REGISTRY[name] = cls
        return cls
    return decorator