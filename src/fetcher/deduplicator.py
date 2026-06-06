from sqlalchemy.orm import Session
from sqlalchemy import select
from src.shared.models import RawItem


def filter_new_items(session: Session, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    ids = [c["external_id"] for c in candidates]
    existing = set(
        row[0] for row in session.execute(
            select(RawItem.external_id).where(RawItem.external_id.in_(ids))
        )
    )
    return [c for c in candidates if c["external_id"] not in existing]
