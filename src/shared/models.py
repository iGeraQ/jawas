import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class RawItem(Base):
    __tablename__ = "raw_items"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_new_uuid)
    external_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    drafts: Mapped[list["Draft"]] = relationship(back_populates="raw_item")


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_new_uuid)
    raw_item_id: Mapped[str] = mapped_column(ForeignKey("raw_items.id"), nullable=False)
    network: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    edited_content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending_review")
    telegram_msg_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    raw_item: Mapped["RawItem"] = relationship(back_populates="drafts")
    published_post: Mapped["PublishedPost | None"] = relationship(back_populates="draft")


class PublishedPost(Base):
    __tablename__ = "published_posts"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=_new_uuid)
    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    network: Mapped[str] = mapped_column(String, nullable=False)
    network_post_id: Mapped[str] = mapped_column(String, nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    url: Mapped[str | None] = mapped_column(Text)

    draft: Mapped["Draft"] = relationship(back_populates="published_post")
