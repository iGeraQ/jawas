"""Validates the pipeline locally without real external API calls."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.shared.db import engine, get_session
from src.shared.models import Base, RawItem
from src.fetcher.deduplicator import filter_new_items
from src.enricher.url_resolver import resolve_url
from src.publisher.base import SocialNetworkProvider

Base.metadata.create_all(engine)


def test_deduplication():
    session = get_session()
    items = [{"external_id": "smoke_test_1", "source": "rss", "url": "https://example.com", "title": "Test"}]

    session.query(RawItem).filter_by(external_id="smoke_test_1").delete()
    session.commit()

    new = filter_new_items(session, items)
    assert len(new) == 1, "First pass: item should be new"

    db_item = RawItem(**items[0])
    session.add(db_item)
    session.commit()

    new2 = filter_new_items(session, items)
    assert len(new2) == 0, "Second pass: item should be deduplicated"
    session.close()
    print("Deduplication: OK")


def test_provider_interface():
    class DummyProvider(SocialNetworkProvider):
        def publish(self, content: str) -> str:
            return "post_123"
    p = DummyProvider()
    assert p.publish("hello") == "post_123"
    print("SocialNetworkProvider interface: OK")


def test_url_resolver_passthrough():
    # no network: verifies that errors return the original URL
    url = resolve_url("not-a-real-url")
    assert url == "not-a-real-url"
    print("URL resolver fallback: OK")


if __name__ == "__main__":
    test_deduplication()
    test_provider_interface()
    test_url_resolver_passthrough()
    print("\nAll smoke tests passed")
