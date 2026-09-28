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


@pytest.fixture
def filter_articles(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> tuple[list[Article], dict[str, str]]:
    """필터별 일치 게시글과 복합 필터의 일부 조건에만 일치하는 게시글을 준비한다."""
    articles = _store_articles(test_session_factory, list(range(8)))
    tokens = {username: _register(client, username) for username in ["fan", "viewer"]}
    with test_session_factory() as session:
        writer = session.scalar(select(User).where(User.username == "writer"))
        fan = session.scalar(select(User).where(User.username == "fan"))
        viewer = session.scalar(select(User).where(User.username == "viewer"))
        assert writer is not None and fan is not None and viewer is not None
        other_writer = User(
            username="other_writer",
            email="other_writer@example.com",
            password_hash="not-for-login",
        )
        topic = Tag(name="topic")
        extra = Tag(name="extra")
        session.add_all([other_writer, topic, extra])
        session.flush()
        session.add_all(articles[4:])
        for article in articles[4:]:
            article.author_id = other_writer.id
        for index in [0, 1, 2, 4, 6]:
            session.add(
                ArticleTag(article_id=articles[index].id, tag_id=topic.id, position=0)
            )
        for index in [0, 3, 5, 7]:
            session.add(
                ArticleTag(
                    article_id=articles[index].id,
                    tag_id=extra.id,
                    position=1 if index == 0 else 0,
                )
            )
        for index in [0, 1, 3, 4, 5]:
            session.add(ArticleFavorite(user_id=fan.id, article_id=articles[index].id))
        for index in [0, 7]:
            session.add(
                ArticleFavorite(user_id=viewer.id, article_id=articles[index].id)
            )
        session.add(UserFollow(follower_id=viewer.id, followed_id=writer.id))
        session.commit()
    return articles, tokens


@pytest.fixture
def feed_articles(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> tuple[list[Article], dict[str, str]]:
    """요청자별 팔로우, 반대 방향의 팔로우와 서로 다른 작성자의 게시글을 준비한다."""
    articles = _store_articles(test_session_factory, [2, 0, 2, 1, 3, 4])
    tokens = {username: _register(client, username) for username in ["viewer", "other"]}
    with test_session_factory() as session:
        writer = session.scalar(select(User).where(User.username == "writer"))
        viewer = session.scalar(select(User).where(User.username == "viewer"))
        other = session.scalar(select(User).where(User.username == "other"))
        assert writer is not None and viewer is not None and other is not None
        second_writer = User(
            username="second_writer",
            email="second_writer@example.com",
            password_hash="not-for-login",
            bio="Second writer bio",
        )
        unfollowed_writer = User(
            username="unfollowed_writer",
            email="unfollowed_writer@example.com",
            password_hash="not-for-login",
        )
        first_tag = Tag(name="first")
        second_tag = Tag(name="second")
        session.add_all([second_writer, unfollowed_writer, first_tag, second_tag])
        session.flush()
        session.add_all(articles[2:])
        for article in articles[2:4]:
            article.author_id = second_writer.id
        articles[4].author_id = unfollowed_writer.id
        articles[5].author_id = viewer.id
        session.add_all(
            [
                UserFollow(follower_id=viewer.id, followed_id=writer.id),
                UserFollow(follower_id=viewer.id, followed_id=second_writer.id),
                UserFollow(follower_id=other.id, followed_id=unfollowed_writer.id),
                UserFollow(follower_id=unfollowed_writer.id, followed_id=viewer.id),
                ArticleTag(article_id=articles[0].id, tag_id=second_tag.id, position=0),
                ArticleTag(article_id=articles[0].id, tag_id=first_tag.id, position=1),
                ArticleTag(article_id=articles[2].id, tag_id=first_tag.id, position=0),
                ArticleFavorite(user_id=viewer.id, article_id=articles[0].id),
                ArticleFavorite(user_id=viewer.id, article_id=articles[4].id),
                ArticleFavorite(user_id=other.id, article_id=articles[0].id),
                ArticleFavorite(user_id=other.id, article_id=articles[2].id),
                ArticleFavorite(user_id=other.id, article_id=articles[5].id),
            ]
        )
        session.commit()
    return articles, tokens


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


@pytest.mark.parametrize(
    "filters,expected_indices",
    [
        ({"tag": "topic"}, [6, 4, 2, 1, 0]),
        ({"author": "writer"}, [3, 2, 1, 0]),
        ({"author": "other_writer"}, [7, 6, 5, 4]),
        ({"favorited": "fan"}, [5, 4, 3, 1, 0]),
    ],
)
def test_article_filters_select_only_matching_articles(
    client: TestClient,
    filter_articles: tuple[list[Article], dict[str, str]],
    filters: dict[str, str],
    expected_indices: list[int],
) -> None:
    """지정한 태그가 있거나, 지정한 작성자가 썼거나, 지정한 사용자가 즐겨찾기한 글을 필터별로 조회한다."""
    articles, _ = filter_articles
    response = client.get("/api/articles", params=filters)
    assert response.status_code == 200
    items = response.json()["articles"]
    assert [item["slug"] for item in items] == [
        articles[index].slug for index in expected_indices
    ]
    if "tag" in filters:
        assert items[-1]["tagList"] == ["topic", "extra"]


@pytest.mark.parametrize(
    "filters,expected_indices",
    [
        ({"tag": "topic", "author": "writer"}, [2, 1, 0]),
        ({"tag": "topic", "favorited": "fan"}, [4, 1, 0]),
        ({"author": "writer", "favorited": "fan"}, [3, 1, 0]),
        ({"tag": "topic", "author": "writer", "favorited": "fan"}, [1, 0]),
    ],
)
def test_combined_article_filters_require_every_condition(
    client: TestClient,
    filter_articles: tuple[list[Article], dict[str, str]],
    filters: dict[str, str],
    expected_indices: list[int],
) -> None:
    """필터를 함께 지정하면 모든 조건에 일치하는 게시글만 반환한다."""
    articles, _ = filter_articles
    response = client.get("/api/articles", params=filters)
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["articles"]] == [
        articles[index].slug for index in expected_indices
    ]


@pytest.mark.parametrize(
    "filters",
    [
        {"tag": "missing"},
        {"author": "missing"},
        {"favorited": "missing"},
        {"tag": ""},
        {"author": ""},
        {"favorited": ""},
        {"tag": "topic", "author": "other_writer", "favorited": "viewer"},
    ],
)
def test_article_filters_without_matches_return_empty_results(
    client: TestClient,
    filter_articles: tuple[list[Article], dict[str, str]],
    filters: dict[str, str],
) -> None:
    """필터 조건에 일치하는 게시글이 없으면 빈 목록과 전체 게시글 수 0을 반환한다."""
    response = client.get("/api/articles", params=filters)
    assert response.status_code == 200
    assert response.json() == {"articles": [], "articlesCount": 0}


@pytest.mark.parametrize(
    "filters,expected_count",
    [
        ({"tag": "topic"}, 5),
        ({"author": "writer"}, 4),
        ({"favorited": "fan"}, 5),
        ({"tag": "topic", "author": "writer", "favorited": "fan"}, 2),
    ],
)
def test_articles_count_returns_total_filtered_article_count(
    client: TestClient,
    filter_articles: tuple[list[Article], dict[str, str]],
    filters: dict[str, str],
    expected_count: int,
) -> None:
    """articlesCount는 필터에 일치하는 전체 게시글 수를 반환한다."""
    for pagination in [
        {},
        {"limit": 1, "offset": 0},
        {"limit": 2, "offset": 1},
        {"limit": 1, "offset": expected_count},
        {"limit": 1, "offset": 100},
    ]:
        response = client.get("/api/articles", params={**filters, **pagination})
        assert response.status_code == 200
        assert response.json()["articlesCount"] == expected_count


def test_filtered_article_pages_return_only_matching_slices(
    client: TestClient,
    filter_articles: tuple[list[Article], dict[str, str]],
) -> None:
    """필터에 일치하는 목록을 페이지로 나누며, 모든 페이지를 합치면 해당 글이 순서대로 한 번씩 나온다."""
    articles, _ = filter_articles
    filters = {"tag": "topic", "author": "writer", "favorited": "fan"}
    expected_slugs = [articles[index].slug for index in [1, 0]]
    combined = []
    for offset in [0, 1, 2, 100]:
        response = client.get(
            "/api/articles", params={**filters, "limit": 1, "offset": offset}
        )
        assert response.status_code == 200
        slugs = [item["slug"] for item in response.json()["articles"]]
        assert slugs == expected_slugs[offset : offset + 1]
        combined.extend(slugs)
    assert combined == expected_slugs


def test_favorited_filter_user_is_independent_of_viewer_state(
    client: TestClient,
    filter_articles: tuple[list[Article], dict[str, str]],
) -> None:
    """지정한 사용자의 즐겨찾기 목록을 조회해도, 팔로우·즐겨찾기 여부는 실제 조회자에 맞게 표시한다."""
    articles, tokens = filter_articles
    expected_indices = [5, 4, 3, 1, 0]
    for token, favorites, follows in [
        (tokens["fan"], [True] * 5, [False] * 5),
        (
            tokens["viewer"],
            [False, False, False, False, True],
            [False, False, True, True, True],
        ),
        (None, [False] * 5, [False] * 5),
    ]:
        response = client.get(
            "/api/articles",
            params={"favorited": "fan"},
            headers={"Authorization": f"Token {token}"} if token else {},
        )
        assert response.status_code == 200
        items = response.json()["articles"]
        assert [item["slug"] for item in items] == [
            articles[index].slug for index in expected_indices
        ]
        assert [item["favorited"] for item in items] == favorites
        assert [item["author"]["following"] for item in items] == follows
        assert [item["favoritesCount"] for item in items] == [1, 1, 1, 1, 2]


@pytest.mark.parametrize("authorization", ["", "Token invalid", "Bearer invalid"])
def test_article_list_rejects_invalid_authentication(
    client: TestClient,
    authorization: str,
) -> None:
    """목록은 인증 헤더를 생략할 수 있지만, 전달한 인증 헤더가 잘못되면 401로 거부한다."""
    response = client.get("/api/articles", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json() == {"errors": {"token": ["is invalid"]}}


def test_feed_selects_only_articles_by_authors_the_viewer_follows(
    client: TestClient,
    feed_articles: tuple[list[Article], dict[str, str]],
) -> None:
    """피드는 조회한 사용자가 팔로우한 작성자의 게시글만 반환한다."""
    articles, tokens = feed_articles
    for username, expected_indices in [("viewer", [0, 1, 2, 3]), ("other", [4])]:
        response = client.get(
            "/api/articles/feed", headers={"Authorization": f"Token {tokens[username]}"}
        )
        assert response.status_code == 200
        items = response.json()["articles"]
        assert {item["slug"] for item in items} == {
            articles[index].slug for index in expected_indices
        }
        assert len(items) == len(expected_indices)


def test_feed_orders_by_creation_time_and_id_descending(
    client: TestClient,
    feed_articles: tuple[list[Article], dict[str, str]],
) -> None:
    """피드는 최신 작성 순으로 조회되며, 작성 시각이 같으면 내부 게시글 ID가 큰 글부터 나온다."""
    articles, tokens = feed_articles
    response = client.get(
        "/api/articles/feed", headers={"Authorization": f"Token {tokens['viewer']}"}
    )
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["articles"]] == [
        articles[index].slug for index in [2, 0, 3, 1]
    ]


def test_feed_pages_return_expected_slices_without_duplicates_or_omissions(
    client: TestClient,
    feed_articles: tuple[list[Article], dict[str, str]],
) -> None:
    """피드를 페이지별로 조회하면 기대한 목록 구간을 반환하며, 모든 글이 순서대로 한 번씩 나온다."""
    articles, tokens = feed_articles
    expected_slugs = [articles[index].slug for index in [2, 0, 3, 1]]
    for limit in [1, 2]:
        combined = []
        for offset in [*range(0, 4, limit), 4, 100]:
            response = client.get(
                "/api/articles/feed",
                params={"limit": limit, "offset": offset},
                headers={"Authorization": f"Token {tokens['viewer']}"},
            )
            assert response.status_code == 200
            slugs = [item["slug"] for item in response.json()["articles"]]
            assert slugs == expected_slugs[offset : offset + limit]
            combined.extend(slugs)
        assert combined == expected_slugs


def test_feed_articles_count_returns_total_followed_author_article_count(
    client: TestClient,
    feed_articles: tuple[list[Article], dict[str, str]],
) -> None:
    """articlesCount는 조회자가 팔로우한 작성자들의 전체 게시글 수를 반환한다."""
    _, tokens = feed_articles
    for params in [
        {},
        {"limit": 1, "offset": 0},
        {"limit": 2, "offset": 1},
        {"limit": 1, "offset": 4},
        {"limit": 1, "offset": 100},
    ]:
        response = client.get(
            "/api/articles/feed",
            params=params,
            headers={"Authorization": f"Token {tokens['viewer']}"},
        )
        assert response.status_code == 200
        assert response.json()["articlesCount"] == 4


def test_feed_default_page_returns_twenty_articles_and_allows_larger_limits(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """피드의 기본 페이지는 게시글 20개를 반환하며, limit을 늘리면 더 많이 조회할 수 있다."""
    _store_articles(test_session_factory, [0] * 25)
    token = _register(client, "viewer")
    headers = {"Authorization": f"Token {token}"}
    followed = client.post("/api/profiles/writer/follow", headers=headers)
    assert followed.status_code == 200
    default = client.get("/api/articles/feed", headers=headers)
    larger = client.get("/api/articles/feed", params={"limit": 25}, headers=headers)
    assert default.status_code == larger.status_code == 200
    assert len(default.json()["articles"]) == 20
    assert len(larger.json()["articles"]) == 25


@pytest.mark.parametrize("follows_empty_author", [False, True])
def test_feed_without_target_articles_returns_empty_results(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    follows_empty_author: bool,
) -> None:
    """팔로우한 작성자의 게시글이 없으면 피드는 빈 목록과 articlesCount 0을 반환한다."""
    _store_articles(test_session_factory, [0, 1])
    token = _register(client, "viewer")
    headers = {"Authorization": f"Token {token}"}
    if follows_empty_author:
        _register(client, "empty_author")
        followed = client.post("/api/profiles/empty_author/follow", headers=headers)
        assert followed.status_code == 200
    response = client.get("/api/articles/feed", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"articles": [], "articlesCount": 0}


def test_follow_changes_update_feed_in_subsequent_requests(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """팔로우하면 작성자의 기존 글이 다음 피드에 나오고, 해제하면 다음 피드에서 제외된다."""
    articles = _store_articles(test_session_factory, [0, 1])
    viewer_token = _register(client, "viewer")
    other_token = _register(client, "other")
    viewer_headers = {"Authorization": f"Token {viewer_token}"}
    other_headers = {"Authorization": f"Token {other_token}"}
    other_follow = client.post("/api/profiles/writer/follow", headers=other_headers)
    assert other_follow.status_code == 200
    initial = client.get("/api/articles/feed", headers=viewer_headers)
    assert initial.status_code == 200
    assert initial.json() == {"articles": [], "articlesCount": 0}
    for method, expected_indices in [("POST", [1, 0]), ("DELETE", [])]:
        changed = client.request(
            method, "/api/profiles/writer/follow", headers=viewer_headers
        )
        assert changed.status_code == 200
        response = client.get("/api/articles/feed", headers=viewer_headers)
        assert response.status_code == 200
        assert [item["slug"] for item in response.json()["articles"]] == [
            articles[index].slug for index in expected_indices
        ]
        assert response.json()["articlesCount"] == len(expected_indices)
    other_feed = client.get("/api/articles/feed", headers=other_headers)
    assert other_feed.status_code == 200
    assert [item["slug"] for item in other_feed.json()["articles"]] == [
        articles[index].slug for index in [1, 0]
    ]
    assert other_feed.json()["articlesCount"] == 2


def test_feed_shows_public_fields_and_viewer_relationships(
    client: TestClient,
    feed_articles: tuple[list[Article], dict[str, str]],
) -> None:
    """피드는 게시글 본문을 제외한 목록 응답 정보를 반환한다.

    조회자의 작성자 팔로우·즐겨찾기 여부와 즐겨찾기한 사용자 수를 정확히 표시한다.
    """
    articles, tokens = feed_articles
    response = client.get(
        "/api/articles/feed", headers={"Authorization": f"Token {tokens['viewer']}"}
    )
    assert response.status_code == 200
    assert response.json()["articles"] == [
        _expected_item(
            articles[2],
            username="second_writer",
            bio="Second writer bio",
            image=None,
            tags=["first"],
            following=True,
            favorites_count=1,
        ),
        _expected_item(
            articles[0],
            tags=["second", "first"],
            following=True,
            favorited=True,
            favorites_count=2,
        ),
        _expected_item(
            articles[3],
            username="second_writer",
            bio="Second writer bio",
            image=None,
            following=True,
        ),
        _expected_item(articles[1], following=True),
    ]


@pytest.mark.parametrize(
    "authorization,message",
    [
        (None, "is missing"),
        ("", "is missing"),
        ("Token invalid", "is invalid"),
        ("Bearer invalid", "is invalid"),
    ],
)
def test_feed_requires_valid_authentication(
    client: TestClient,
    authorization: str | None,
    message: str,
) -> None:
    """피드는 인증을 요구하며, 인증 헤더가 없거나 잘못되면 기존 token 오류와 함께 401을 반환한다."""
    response = client.get(
        "/api/articles/feed",
        headers={"Authorization": authorization} if authorization is not None else {},
    )
    assert response.status_code == 401
    assert response.json() == {"errors": {"token": [message]}}


@pytest.mark.parametrize("path", ["/api/articles", "/api/articles/feed"])
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
    path: str,
    field: str,
    value: str,
) -> None:
    """limit은 1 이상의 정수, offset은 0 이상의 정수여야 하며 잘못된 값은 해당 필드 오류로 반환한다."""
    headers = {}
    if path == "/api/articles/feed":
        headers = {"Authorization": f"Token {_register(client, 'viewer')}"}
    response = client.get(path, params={field: value}, headers=headers)
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert set(errors) == {field}
    assert errors[field] and all(isinstance(message, str) for message in errors[field])
