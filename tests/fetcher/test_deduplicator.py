from src.fetcher.deduplicator import filter_new_items
from src.shared.models import RawItem


def test_filter_new_items_returns_only_unseen(db_session):
    db_session.add(RawItem(external_id="existing123", source="rss", url="u1", title="t1"))
    db_session.flush()

    candidates = [
        {"external_id": "existing123", "source": "rss", "url": "u1", "title": "t1"},
        {"external_id": "new456", "source": "hn", "url": "u2", "title": "t2"},
    ]
    result = filter_new_items(db_session, candidates)
    assert len(result) == 1
    assert result[0]["external_id"] == "new456"


def test_filter_new_items_empty_candidates(db_session):
    assert filter_new_items(db_session, []) == []
