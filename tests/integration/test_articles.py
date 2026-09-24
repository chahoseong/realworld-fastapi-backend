from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.articles.models import Article, ArticleTag, Tag
from app.users.models import User


def _register_user(client: TestClient) -> tuple[str, str]:
    username = f"article-{uuid4().hex}"
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
    assert response.status_code == status.HTTP_201_CREATED
    return username, response.json()["user"]["token"]


def _article_input(title: str, tags: list[str] | None = None) -> dict[str, object]:
    article: dict[str, object] = {
        "title": title,
        "description": "A description",
        "body": "An article body",
    }
    if tags is not None:
        article["tagList"] = tags
    return {"article": article}


def _create_article(
    client: TestClient,
    token: str,
    title: str,
    tags: list[str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/articles",
        headers={"Authorization": f"Token {token}"},
        json=_article_input(title, tags),
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, object], response.json()["article"])


def _counts(session: Session) -> tuple[int, int, int, int]:
    counts = tuple(
        session.scalar(select(func.count()).select_from(model))
        for model in (User, Article, Tag, ArticleTag)
    )
    assert all(count is not None for count in counts)
    return counts  # type: ignore[return-value]


@pytest.mark.parametrize(
    "same_title",
    [False, True],
    ids=["different-titles", "same-title"],
)
def test_article_slugs_identify_distinct_articles(
    client: TestClient,
    same_title: bool,
) -> None:
    """제목이 같거나 다른 두 게시글을 각각 고유한 slug로 조회한다."""
    # Arrange
    _, token = _register_user(client)
    first_title = f"First title {uuid4().hex}"
    second_title = first_title if same_title else f"Second title {uuid4().hex}"

    # Act
    first = _create_article(client, token, first_title)
    second = _create_article(client, token, second_title)
    first_read = client.get(f"/api/articles/{first['slug']}")
    second_read = client.get(f"/api/articles/{second['slug']}")

    # Assert
    assert first["slug"] != second["slug"]
    assert first_read.status_code == status.HTTP_200_OK
    assert second_read.status_code == status.HTTP_200_OK
    assert first_read.json()["article"] == first
    assert second_read.json()["article"] == second


def test_multiple_articles_can_share_one_tag(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """두 게시글이 같은 태그를 사용해도 태그와 연결 관계가 유지된다."""
    # Arrange
    _, token = _register_user(client)
    tag = f"shared-{uuid4().hex}"

    # Act
    first = _create_article(client, token, f"First {uuid4().hex}", [tag])
    second = _create_article(client, token, f"Second {uuid4().hex}", [tag])
    with test_session_factory() as session:
        tags = session.scalars(select(Tag).where(Tag.name == tag)).all()
        links = session.scalars(
            select(ArticleTag)
            .join(Tag, Tag.id == ArticleTag.tag_id)
            .where(Tag.name == tag)
        ).all()

    # Assert
    assert first["tagList"] == [tag]
    assert second["tagList"] == [tag]
    assert len(tags) == 1
    assert len(links) == 2
    assert links[0].article_id != links[1].article_id


def test_omitted_tag_list_is_empty_on_create_and_read(
    client: TestClient,
) -> None:
    """tagList를 생략하면 생성 응답과 재조회에서 태그 목록이 비어 있다."""
    # Arrange
    _, token = _register_user(client)

    # Act
    created = _create_article(client, token, f"Untagged {uuid4().hex}")
    read = client.get(f"/api/articles/{created['slug']}")

    # Assert
    assert created["tagList"] == []
    assert read.json()["article"]["tagList"] == []


def test_slug_collision_creates_only_requested_articles_with_distinct_slugs(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """slug가 충돌해도 요청한 두 게시글만 서로 다른 slug로 생성된다."""
    # Arrange
    _, token = _register_user(client)
    title = f"Collision {uuid4().hex}"
    tag = f"collision-{uuid4().hex}"
    ids = iter((UUID(int=1), UUID(int=1), UUID(int=2)))

    # Act
    with monkeypatch.context() as patch:
        patch.setattr("app.articles.router.uuid4", lambda: next(ids))
        first = _create_article(client, token, title, [tag])
        second = _create_article(client, token, title, [tag])

    with test_session_factory() as session:
        articles = session.scalars(select(Article).where(Article.title == title)).all()
        tags = session.scalars(select(Tag).where(Tag.name == tag)).all()
        links = session.scalars(
            select(ArticleTag).where(
                ArticleTag.article_id.in_(article.id for article in articles)
            )
        ).all()

    # Assert
    assert first["slug"] != second["slug"]
    assert len(articles) == 2
    assert len(tags) == 1
    assert len(links) == 2


def test_create_article_without_auth_returns_401_without_new_records(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """인증 없이 게시글을 생성하면 401을 반환하고 신규 레코드를 만들지 않는다."""
    # Arrange
    with test_session_factory() as session:
        before = _counts(session)

    # Act
    unauthorized = client.post("/api/articles", json=_article_input("No auth"))

    # Assert
    assert unauthorized.status_code == status.HTTP_401_UNAUTHORIZED
    assert unauthorized.json() == {"errors": {"token": ["is missing"]}}
    with test_session_factory() as session:
        assert _counts(session) == before


@pytest.mark.parametrize(
    "invalid_field",
    ["title", "description", "body", "tagList"],
    ids=["blank-title", "blank-description", "blank-body", "null-tag-list"],
)
def test_create_article_with_invalid_field_returns_422_without_new_records(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    invalid_field: str,
) -> None:
    """필수 텍스트가 공백이거나 tagList가 null이면 422를 반환하고 저장하지 않는다."""
    # Arrange
    _, token = _register_user(client)
    with test_session_factory() as session:
        before = _counts(session)
    payload = _article_input(f"Invalid {uuid4().hex}", [f"unused-{uuid4().hex}"])
    article = cast(dict[str, object], payload["article"])
    article[invalid_field] = None if invalid_field == "tagList" else "   "

    # Act
    invalid = client.post(
        "/api/articles",
        headers={"Authorization": f"Token {token}"},
        json=payload,
    )

    # Assert
    assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    if invalid_field == "tagList":
        assert "tagList" in invalid.json()["errors"]
    else:
        assert invalid.json() == {"errors": {invalid_field: ["can't be blank"]}}
    with test_session_factory() as session:
        assert _counts(session) == before


def test_get_unknown_article_returns_404(client: TestClient) -> None:
    """존재하지 않는 slug를 조회하면 404와 게시글 미존재 오류를 반환한다."""
    # Arrange
    missing_slug = f"missing-{uuid4().hex}"

    # Act
    missing = client.get(f"/api/articles/{missing_slug}")

    # Assert
    assert missing.status_code == status.HTTP_404_NOT_FOUND
    assert missing.json() == {"errors": {"article": ["not found"]}}


def test_article_commit_failure_leaves_no_new_records_and_allows_retry(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """커밋 실패 후 신규 레코드가 남지 않고 같은 요청을 다시 보내면 성공한다."""
    # Arrange
    _, token = _register_user(server_error_client)
    title = f"Rollback {uuid4().hex}"
    tag = f"rollback-{uuid4().hex}"
    with test_session_factory() as session:
        before = _counts(session)

    def fail_after_flush(session: Session) -> None:
        session.flush()
        raise RuntimeError("simulated commit failure")

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        failed = server_error_client.post(
            "/api/articles",
            headers={"Authorization": f"Token {token}"},
            json=_article_input(title, [tag]),
        )
    with test_session_factory() as session:
        after_failure = _counts(session)
        failed_article = session.scalar(select(Article).where(Article.title == title))
        failed_tag = session.scalar(select(Tag).where(Tag.name == tag))
    recovered = _create_article(server_error_client, token, title, [tag])

    # Assert
    assert failed.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert after_failure == before
    assert failed_article is None
    assert failed_tag is None
    assert recovered["title"] == title
