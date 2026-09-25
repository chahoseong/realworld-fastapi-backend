from datetime import UTC, datetime

from fastapi import APIRouter, status
from sqlalchemy import select

from app.articles.lookup import find_article_by_public_slug
from app.articles.models import Article
from app.comments.models import Comment
from app.comments.schemas import (
    CommentPayload,
    CommentResponse,
    CommentsResponse,
    NewCommentRequest,
)
from app.database import SessionDep
from app.errors import ApiError
from app.users.auth import CurrentUserDep, OptionalUserDep
from app.users.models import User
from app.users.schemas import ProfilePayload

router = APIRouter(prefix="/api", tags=["comments"])


def _comment_payload(comment: Comment, author: User) -> CommentPayload:
    return CommentPayload(
        id=comment.id,
        body=comment.body,
        createdAt=comment.created_at,
        updatedAt=comment.updated_at,
        author=ProfilePayload(
            username=author.username,
            bio=author.bio,
            image=author.image,
            following=False,
        ),
    )


@router.post("/articles/{slug}/comments", status_code=status.HTTP_201_CREATED)
def create_comment(
    slug: str,
    request: NewCommentRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> CommentResponse:
    author, _ = current_user
    article = session.scalar(select(Article).where(Article.slug == slug))
    if article is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, {"article": ["not found"]})

    now = datetime.now(UTC)
    comment = Comment(
        article_id=article.id,
        author_id=author.id,
        body=request.comment.body,
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(comment)
        session.flush()
        response = CommentResponse(comment=_comment_payload(comment, author))
        session.commit()
        return response
    except Exception:
        session.rollback()
        raise


@router.get("/articles/{slug}/comments")
def list_comments(
    slug: str,
    _viewer: OptionalUserDep,
    session: SessionDep,
) -> CommentsResponse:
    article = find_article_by_public_slug(session, slug)
    if article is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, {"article": ["not found"]})

    rows = session.execute(
        select(Comment, User)
        .join(User, User.id == Comment.author_id)
        .where(Comment.article_id == article.id)
        .order_by(Comment.id)
    ).all()
    return CommentsResponse(
        comments=[_comment_payload(comment, author) for comment, author in rows]
    )


@router.delete("/articles/{slug}/comments/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    slug: str,
    id: int,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    author, _ = current_user
    article = session.scalar(select(Article).where(Article.slug == slug))
    if article is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, {"article": ["not found"]})

    comment = session.scalar(
        select(Comment)
        .where(Comment.id == id, Comment.article_id == article.id)
        .with_for_update()
    )
    if comment is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, {"comment": ["not found"]})
    if comment.author_id != author.id:
        raise ApiError(status.HTTP_403_FORBIDDEN, {"comment": ["forbidden"]})

    try:
        session.delete(comment)
        session.commit()
    except Exception:
        session.rollback()
        raise
