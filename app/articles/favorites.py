from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.articles.models import ArticleFavorite


def favorite_state(
    session: Session, viewer_id: int | None, article_id: int
) -> tuple[bool, int]:
    favorites_count, viewer_count = session.execute(
        select(
            func.count(),
            func.count().filter(ArticleFavorite.user_id == viewer_id),
        )
        .select_from(ArticleFavorite)
        .where(ArticleFavorite.article_id == article_id)
    ).one()
    return viewer_count > 0, favorites_count
