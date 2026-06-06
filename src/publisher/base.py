from abc import ABC, abstractmethod


class SocialNetworkProvider(ABC):
    @abstractmethod
    def publish(self, content: str) -> str:
        """Publish content and return the network's post ID."""
        ...
