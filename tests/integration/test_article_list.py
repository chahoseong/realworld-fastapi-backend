from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.articles.models import Article, ArticleFavorite, ArticleTag, Tag
from app.users.models import User, UserFollow


@pytest.fixture
def test_session_factory(test_database_url: str) -> Generator[sessionmaker[Session]]:
    """목록의 전체 건수와 순서를 다른 테스트 데이터 없이 검증한다."""
    schema = f"article_list_{uuid4().hex}"
    admin_engine = create_engine(test_database_url)
    engine = create_engine(
        test_database_url, connect_args={"options": f"-csearch_path={schema}"}
    )
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        with engine.begin() as connection:
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin_engine.dispose()


def _store_articles(
    factory: sessionmaker[Session], creation_days: list[int]
) -> list[Article]:
    with factory() as session:
        author = User(
            username="writer",
            email="writer@example.com",
            password_hash="not-for-login",
            bio="Writer bio",
            image="https://example.com/writer.png",
        )
        session.add(author)
        session.flush()
        articles = []
        for index, day in enumerate(creation_days, start=1):
            article = Article(
                author_id=author.id,
                public_id=UUID(int=index),
                slug=f"title-{index}-{UUID(int=index).hex}",
                title=f"Title {index}",
                description=f"Description {index}",
                body=f"Private body {index}",
                created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
                updated_at=datetime(2026, 2, 1, tzinfo=UTC) + timedelta(days=index),
            )
            session.add(article)
            articles.append(article)
        session.commit()
        return articles


def _expected_item(
    article: Article,
    *,
    username: str = "writer",
    bio: str | None = "Writer bio",
    image: str | None = "https://example.com/writer.png",
    tags: list[str] | None = None,
    following: bool = False,
    favorited: bool = False,
    favorites_count: int = 0,
) -> dict[str, object]:
    return {
        "slug": article.slug,
        "title": article.title,
        "description": article.description,
        "tagList": tags or [],
        "createdAt": article.created_at.isoformat().replace("+00:00", "Z"),
        "updatedAt": article.updated_at.isoformat().replace("+00:00", "Z"),
        "favorited": favorited,
        "favoritesCount": favorites_count,
        "author": {
            "username": username,
            "bio": bio,
            "image": image,
            "following": following,
        },
    }


def _register(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/users",
        json={
            "user": {
                "username": username,
                "email": f"{username}@example.com",
                "password": "password123",
            }
        },
    )
    assert response.status_code == 201
    return cast(str, response.json()["user"]["token"])


def test_article_list_orders_by_creation_time_and_id_descending(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """게시글은 최신 작성 순으로 조회되며, 작성 시각이 같으면 내부 게시글 ID가 큰 게시글부터 나온다."""
    articles = _store_articles(test_session_factory, [2, 0, 2, 1, 0])
    expected_slugs = [articles[index].slug for index in [2, 0, 3, 4, 1]]
    response = client.get("/api/articles")
    assert response.status_code == 200
    assert [
        article["slug"] for article in response.json()["articles"]
    ] == expected_slugs


def test_article_pages_return_expected_slices_without_duplicates_or_omissions(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """각 페이지는 정해진 목록 구간을 반환하며, 모든 페이지를 합치면 각 게시글이 순서대로 한 번씩 나온다."""
    articles = _store_articles(test_session_factory, [2, 0, 2, 1, 0])
    expected_slugs = [articles[index].slug for index in [2, 0, 3, 4, 1]]
    for limit in [1, 2]:
        combined = []
        for offset in range(0, 5, limit):
            page = client.get(
                "/api/articles", params={"limit": limit, "offset": offset}
            )
            assert page.status_code == 200
            slugs = [article["slug"] for article in page.json()["articles"]]
            assert slugs == expected_slugs[offset : offset + limit]
            combined.extend(slugs)
        assert combined == expected_slugs


def test_default_page_returns_twenty_articles_and_allows_larger_limits(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """기본 페이지는 게시글 20개를 반환하며, limit을 늘리면 20개보다 많이 조회할 수 있다."""
    _store_articles(test_session_factory, [0] * 25)
    default = client.get("/api/articles")
    larger = client.get("/api/articles", params={"limit": 25})
    assert default.status_code == larger.status_code == 200
    assert len(default.json()["articles"]) == 20
    assert len(larger.json()["articles"]) == 25


def test_article_count_is_independent_of_page_size_and_offset(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """전체 게시글 수는 페이지 크기나 조회 위치와 관계없이 페이지로 나누기 전의 게시글 수다."""
    _store_articles(test_session_factory, [0] * 25)
    for params in [
        {},
        {"limit": 25},
        {"limit": 1, "offset": 0},
        {"limit": 2, "offset": 1},
        {"limit": 2, "offset": 24},
        {"limit": 2, "offset": 25},
        {"limit": 2, "offset": 100},
    ]:
        response = client.get("/api/articles", params=params)
        assert response.status_code == 200
        assert response.json()["articlesCount"] == 25


def test_empty_article_list_returns_zero_count(client: TestClient) -> None:
    """게시글이 없으면 빈 목록과 전체 건수 0을 반환한다."""
    response = client.get("/api/articles")
    assert response.status_code == 200
    assert response.json() == {"articles": [], "articlesCount": 0}


def test_pages_beyond_last_article_are_empty(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """전체 게시글 수 이상의 offset으로 조회하면 빈 게시글 목록을 반환한다."""
    _store_articles(test_session_factory, [2, 0, 2, 1, 0])
    for offset in [5, 100]:
        response = client.get("/api/articles", params={"limit": 2, "offset": offset})
        assert response.status_code == 200
        assert response.json()["articles"] == []


def test_article_list_shows_public_fields_and_viewer_relationships_without_duplicates(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """게시글 목록에서 각 글은 한 번씩 나온다.

    각 글의 공개 정보, 조회자의 작성자 팔로우 여부와 즐겨찾기 여부,
    즐겨찾기한 사용자 수를 정확히 표시한다.
    """
    articles = _store_articles(test_session_factory, [0, 1])
    viewer_token = _register(client, "viewer")
    other_token = _register(client, "other")
    with test_session_factory() as session:
        writer = session.scalar(select(User).where(User.username == "writer"))
        viewer = session.scalar(select(User).where(User.username == "viewer"))
        other = session.scalar(select(User).where(User.username == "other"))
        assert writer is not None and viewer is not None and other is not None
        second_article = session.get(Article, articles[1].id)
        assert second_article is not None
        second_article.author_id = other.id
        second_tag = Tag(name="second")
        first_tag = Tag(name="first")
        session.add_all([second_tag, first_tag])
        session.flush()
        session.add_all(
            [
                ArticleTag(article_id=articles[0].id, tag_id=second_tag.id, position=0),
                ArticleTag(article_id=articles[0].id, tag_id=first_tag.id, position=1),
                UserFollow(follower_id=viewer.id, followed_id=writer.id),
                ArticleFavorite(user_id=viewer.id, article_id=articles[0].id),
                ArticleFavorite(user_id=other.id, article_id=articles[0].id),
                ArticleFavorite(user_id=other.id, article_id=articles[1].id),
            ]
        )
        session.commit()
    for token, follows, favorites in [
        (viewer_token, [True, False], [True, False]),
        (other_token, [False, False], [True, True]),
        (None, [False, False], [False, False]),
    ]:
        response = client.get(
            "/api/articles",
            headers={"Authorization": f"Token {token}"} if token else {},
        )
        assert response.status_code == 200
        assert response.json()["articles"] == [
            _expected_item(
                articles[1],
                username="other",
                bio=None,
                image=None,
                following=follows[1],
                favorited=favorites[1],
                favorites_count=1,
            ),
            _expected_item(
                articles[0],
                tags=["second", "first"],
                following=follows[0],
                favorited=favorites[0],
                favorites_count=2,
            ),
        ]


@pytest.mark.parametrize("authorization", ["", "Token invalid", "Bearer invalid"])
def test_article_list_rejects_invalid_authentication(
    client: TestClient,
    authorization: str,
) -> None:
    """목록은 인증 헤더를 생략할 수 있지만, 전달한 인증 헤더가 잘못되면 401로 거부한다."""
    response = client.get("/api/articles", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json() == {"errors": {"token": ["is invalid"]}}


@pytest.mark.parametrize(
    "field,value",
    [
        ("limit", "0"),
        ("limit", "-1"),
        ("limit", "abc"),
        ("limit", "1.5"),
        ("offset", "-1"),
        ("offset", "abc"),
        ("offset", "1.5"),
    ],
)
def test_invalid_pagination_returns_field_errors(
    client: TestClient,
    field: str,
    value: str,
) -> None:
    """limit은 1 이상의 정수, offset은 0 이상의 정수여야 하며 잘못된 값은 해당 필드 오류로 반환한다."""
    response = client.get("/api/articles", params={field: value})
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert set(errors) == {field}
    assert errors[field] and all(isinstance(message, str) for message in errors[field])
