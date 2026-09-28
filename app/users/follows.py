from sqlalchemy.orm import Session

from app.users.models import UserFollow


def is_following(session: Session, viewer_id: int | None, author_id: int) -> bool:
    if viewer_id is None:
        return False
    return session.get(UserFollow, (viewer_id, author_id)) is not None
