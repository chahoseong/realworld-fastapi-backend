import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.articles.models import Article, ArticleTag, Tag
from app.articles.schemas import (
    ArticleAuthor,
    ArticlePayload,
    ArticleResponse,
    NewArticleRequest,
    TagsResponse,
    UpdateArticleRequest,
)
from app.database import SessionDep
from app.errors import ApiError
from app.users.auth import CurrentUserDep
from app.users.models import User

router = APIRouter(prefix="/api", tags=["articles"])
MAX_SLUG_ATTEMPTS = 3


def _new_slug(title: str, public_id: UUID) -> str:
    title_part = re.sub(r"[\W_]+", "-", title.casefold()).strip("-")[:80].rstrip("-")
    return f"{title_part or 'article'}-{public_id.hex}"


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


def _article_tag_names(session: Session, article_id: int) -> list[str]:
    return list(
        session.scalars(
            select(Tag.name)
            .join(ArticleTag, ArticleTag.tag_id == Tag.id)
            .where(ArticleTag.article_id == article_id)
            .order_by(ArticleTag.position)
        ).all()
    )


def _locked_tags(
    session: Session, names: set[str], create_missing: set[str]
) -> dict[str, Tag]:
    tags: dict[str, Tag] = {}
    for name in sorted(names):
        tag = session.scalar(select(Tag).where(Tag.name == name).with_for_update())
        if tag is None:
            assert name in create_missing
            tag = Tag(name=name)
            session.add(tag)
            session.flush()
        tags[name] = tag
    return tags


def _replace_article_tags(
    session: Session, article_id: int, new_names: list[str]
) -> None:
    old_links = session.scalars(
        select(ArticleTag).where(ArticleTag.article_id == article_id)
    ).all()
    old_names = _article_tag_names(session, article_id)
    tags = _locked_tags(session, set(old_names) | set(new_names), set(new_names))

    for link in old_links:
        session.delete(link)
    session.flush()
    for position, name in enumerate(new_names):
        session.add(
            ArticleTag(article_id=article_id, tag_id=tags[name].id, position=position)
        )
    session.flush()

    for name in set(old_names) - set(new_names):
        tag = tags[name]
        has_link = session.scalar(
            select(ArticleTag.article_id).where(ArticleTag.tag_id == tag.id).limit(1)
        )
        if has_link is None:
            session.delete(tag)


@router.post("/articles", status_code=status.HTTP_201_CREATED)
def create_article(
    request: NewArticleRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ArticleResponse:
    author, _ = current_user
    for attempt in range(MAX_SLUG_ATTEMPTS):
        now = datetime.now(UTC)
        public_id = uuid4()
        article = Article(
            author_id=author.id,
            slug=_new_slug(request.article.title, public_id),
            public_id=public_id,
            title=request.article.title,
            description=request.article.description,
            body=request.article.body,
            created_at=now,
            updated_at=now,
        )
        try:
            session.add(article)
            session.flush()

            tags_by_name = _locked_tags(
                session, set(request.article.tagList), set(request.article.tagList)
            )
            for position, name in enumerate(request.article.tagList):
                session.add(
                    ArticleTag(
                        article_id=article.id,
                        tag_id=tags_by_name[name].id,
                        position=position,
                    )
                )

            response = _article_response(article, author, request.article.tagList)
            session.commit()
            return response
        except IntegrityError as exception:
            session.rollback()
            constraint_name = getattr(
                getattr(exception.orig, "diag", None), "constraint_name", None
            )
            if constraint_name in {
                "uq_articles_slug",
                "uq_articles_public_id",
                "uq_tags_name",
            } and (attempt < MAX_SLUG_ATTEMPTS - 1):
                continue
            raise
        except Exception:
            session.rollback()
            raise

    raise AssertionError("unreachable")


@router.get("/articles/{slug}")
def get_article(slug: str, session: SessionDep) -> ArticleResponse:
    match = re.search(r"-([0-9a-f]{32})$", slug)
    article = (
        session.scalar(
            select(Article).where(Article.public_id == UUID(hex=match.group(1)))
        )
        if match is not None
        else None
    )
    if article is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, {"article": ["not found"]})

    author = session.get(User, article.author_id)
    assert author is not None
    return _article_response(article, author, _article_tag_names(session, article.id))


@router.put("/articles/{slug}")
def update_article(
    slug: str,
    request: UpdateArticleRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ArticleResponse:
    author, _ = current_user
    changes = request.article.model_fields_set

    for attempt in range(MAX_SLUG_ATTEMPTS):
        article = session.scalar(
            select(Article).where(Article.slug == slug).with_for_update()
        )
        if article is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, {"article": ["not found"]})
        if article.author_id != author.id:
            raise ApiError(status.HTTP_403_FORBIDDEN, {"article": ["forbidden"]})

        try:
            if "title" in changes:
                assert request.article.title is not None
                if request.article.title != article.title:
                    article.slug = _new_slug(request.article.title, article.public_id)
                article.title = request.article.title
            if "description" in changes:
                assert request.article.description is not None
                article.description = request.article.description
            if "body" in changes:
                assert request.article.body is not None
                article.body = request.article.body
            if "tagList" in changes:
                assert request.article.tagList is not None
                tag_names = request.article.tagList
                _replace_article_tags(session, article.id, tag_names)
            else:
                tag_names = _article_tag_names(session, article.id)

            article.updated_at = max(
                datetime.now(UTC), article.updated_at + timedelta(microseconds=1)
            )
            response = _article_response(article, author, tag_names)
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


@router.delete("/articles/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_article(
    slug: str,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    author, _ = current_user
    article = session.scalar(
        select(Article).where(Article.slug == slug).with_for_update()
    )
    if article is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, {"article": ["not found"]})
    if article.author_id != author.id:
        raise ApiError(status.HTTP_403_FORBIDDEN, {"article": ["forbidden"]})

    try:
        _replace_article_tags(session, article.id, [])
        session.delete(article)
        session.commit()
    except Exception:
        session.rollback()
        raise


@router.get("/tags")
def get_tags(session: SessionDep) -> TagsResponse:
    names = session.scalars(select(Tag.name).order_by(Tag.name)).all()
    return TagsResponse(tags=list(names))
