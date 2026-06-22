from abc import ABC, abstractmethod
from dataclasses import dataclass


def split_into_thread(text: str, limit: int) -> list[str]:
    """Split text into ordered chunks of at most `limit` characters for threading.

    Length-driven: text that already fits returns a single chunk unchanged, so
    short multi-paragraph posts are NOT threaded. Longer text is greedily packed
    word by word; a single token longer than `limit` (e.g. a giant URL) is
    hard-split as a last resort.

    ponytail: counts raw characters, not platform-weighted length (X counts URLs
    as 23, CJK as 2). Fine for Latin text; may over-split URL-heavy tweets.
    """
    text = text.strip()
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:limit])
            word = word[limit:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= limit:
            current += " " + word
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


@dataclass
class PublishResult:
    post_id: str
    url: str
    post_count: int = 1


class RateLimitExceeded(Exception):
    def __init__(self, wait_seconds: int):
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limit exceeded, retry in {wait_seconds}s")


class SocialNetworkProvider(ABC):
    @abstractmethod
    def publish(self, content: str) -> PublishResult:
        """Publish content and return post metadata."""
        ...


_REGISTRY: dict[str, type[SocialNetworkProvider]] = {}


def register_publisher(name: str):
    def decorator(cls: type[SocialNetworkProvider]) -> type[SocialNetworkProvider]:
        _REGISTRY[name] = cls
        return cls
    return decorator


_INSTANCES: dict[str, SocialNetworkProvider] = {}


def get_provider(name: str) -> SocialNetworkProvider:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown publisher: {name}")
    if name not in _INSTANCES:
        _INSTANCES[name] = _REGISTRY[name]()
    return _INSTANCES[name]
