import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.articles.models import Article


def find_article_by_public_slug(session: Session, slug: str) -> Article | None:
    match = re.search(r"-([0-9a-f]{32})$", slug)
    if match is None:
        return None
    return session.scalar(
        select(Article).where(Article.public_id == UUID(hex=match.group(1)))
    )
