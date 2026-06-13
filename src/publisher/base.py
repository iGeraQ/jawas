from abc import ABC, abstractmethod
from dataclasses import dataclass


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


def get_provider(name: str) -> SocialNetworkProvider:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown publisher: {name}")
    return _REGISTRY[name]()
