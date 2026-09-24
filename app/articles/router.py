import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.articles.models import Article, ArticleTag, Tag
from app.articles.schemas import (
    ArticleAuthor,
    ArticlePayload,
    ArticleResponse,
    NewArticleRequest,
    TagsResponse,
)
from app.database import SessionDep
from app.errors import ApiError
from app.users.auth import CurrentUserDep
from app.users.models import User

router = APIRouter(prefix="/api", tags=["articles"])
MAX_SLUG_ATTEMPTS = 3


def _new_slug(title: str) -> str:
    title_part = re.sub(r"[\W_]+", "-", title.casefold()).strip("-")[:80].rstrip("-")
    return f"{title_part or 'article'}-{uuid4().hex}"


def _article_response(
    article: Article, author: User, tag_names: list[str]
) -> ArticleResponse:
    return ArticleResponse(
        article=ArticlePayload(
            slug=article.slug,
            title=article.title,
            description=article.description,
            body=article.body,
            tagList=tag_names,
            createdAt=article.created_at,
            updatedAt=article.updated_at,
            favorited=False,
            favoritesCount=0,
            author=ArticleAuthor(
                username=author.username,
                bio=author.bio,
                image=author.image,
                following=False,
            ),
        )
    )


@router.post("/articles", status_code=status.HTTP_201_CREATED)
def create_article(
    request: NewArticleRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ArticleResponse:
    author, _ = current_user
    for attempt in range(MAX_SLUG_ATTEMPTS):
        now = datetime.now(UTC)
        article = Article(
            author_id=author.id,
            slug=_new_slug(request.article.title),
            title=request.article.title,
            description=request.article.description,
            body=request.article.body,
            created_at=now,
            updated_at=now,
        )
        try:
            session.add(article)
            session.flush()

            tags_by_name: dict[str, Tag] = {}
            for position, name in enumerate(request.article.tagList):
                tag = tags_by_name.get(name)
                if tag is None:
                    tag = session.scalar(select(Tag).where(Tag.name == name))
                    if tag is None:
                        tag = Tag(name=name)
                        session.add(tag)
                        session.flush()
                    tags_by_name[name] = tag
                session.add(
                    ArticleTag(article_id=article.id, tag_id=tag.id, position=position)
                )

            response = _article_response(article, author, request.article.tagList)
            session.commit()
            return response
        except IntegrityError as exception:
            session.rollback()
            constraint_name = getattr(
                getattr(exception.orig, "diag", None), "constraint_name", None
            )
            if constraint_name in {"uq_articles_slug", "uq_tags_name"} and (
                attempt < MAX_SLUG_ATTEMPTS - 1
            ):
                continue
            raise
        except Exception:
            session.rollback()
            raise

    raise AssertionError("unreachable")


@router.get("/articles/{slug}")
def get_article(slug: str, session: SessionDep) -> ArticleResponse:
    article = session.scalar(select(Article).where(Article.slug == slug))
    if article is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, {"article": ["not found"]})

    author = session.get(User, article.author_id)
    assert author is not None
    tag_names = session.scalars(
        select(Tag.name)
        .join(ArticleTag, ArticleTag.tag_id == Tag.id)
        .where(ArticleTag.article_id == article.id)
        .order_by(ArticleTag.position)
    ).all()
    return _article_response(article, author, list(tag_names))


@router.get("/tags")
def get_tags(session: SessionDep) -> TagsResponse:
    names = session.scalars(select(Tag.name).order_by(Tag.name)).all()
    return TagsResponse(tags=list(names))
