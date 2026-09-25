from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Identity, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_articles_slug"),
        UniqueConstraint("public_id", name="uq_articles_public_id"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    slug: Mapped[str] = mapped_column(Text)
    public_id: Mapped[UUID] = mapped_column(Uuid())
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name", name="uq_tags_name"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class ArticleTag(Base):
    __tablename__ = "article_tags"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), nullable=False)
