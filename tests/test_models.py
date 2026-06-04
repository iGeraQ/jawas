import pytest
from sqlalchemy.exc import IntegrityError

from src.shared.models import Draft, RawItem


def test_raw_item_created_with_defaults(db_session):
    item = RawItem(external_id="hash1", source="rss", url="https://a.com", title="Test")
    db_session.add(item)
    db_session.flush()
    assert item.id is not None
    assert item.status == "pending"


def test_raw_item_external_id_is_unique(db_session):
    db_session.add(RawItem(external_id="dup", source="rss", url="u1", title="t1"))
    db_session.flush()
    db_session.add(RawItem(external_id="dup", source="hn", url="u2", title="t2"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_draft_references_raw_item(db_session):
    item = RawItem(external_id="h2", source="rss", url="u3", title="t3")
    db_session.add(item)
    db_session.flush()
    draft = Draft(raw_item_id=item.id, network="x", content="Draft text")
    db_session.add(draft)
    db_session.flush()
    assert draft.status == "pending_review"
    assert draft.raw_item_id == item.id
