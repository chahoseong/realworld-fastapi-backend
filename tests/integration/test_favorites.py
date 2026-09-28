from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.articles.models import Article, ArticleFavorite
from app.users.models import User


def _register_user(client: TestClient) -> tuple[str, str]:
    username = f"favorite-{uuid4().hex}"
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
    return username, cast(str, response.json()["user"]["token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}"}


def _create_article(client: TestClient, token: str) -> dict[str, object]:
    response = client.post(
        "/api/articles",
        headers=_headers(token),
        json={
            "article": {
                "title": f"Favorite article {uuid4().hex}",
                "description": "Keep description",
                "body": "Keep body",
                "tagList": [f"favorite-{uuid4().hex}"],
            }
        },
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json()["article"])


def _user_id(session: Session, username: str) -> int:
    user_id = session.scalar(select(User.id).where(User.username == username))
    assert user_id is not None
    return user_id


def _article_id(session: Session, slug: str) -> int:
    article_id = session.scalar(select(Article.id).where(Article.slug == slug))
    assert article_id is not None
    return article_id


def _relationships(session: Session, article_ids: list[int]) -> set[tuple[int, int]]:
    return {
        (user_id, article_id)
        for user_id, article_id in session.execute(
            select(ArticleFavorite.user_id, ArticleFavorite.article_id).where(
                ArticleFavorite.article_id.in_(article_ids)
            )
        )
    }


def test_repeated_favorite_and_unfavorite_preserve_relationship_and_count(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """자기 게시글도 즐겨찾기할 수 있다. 반복 추가·해제 후에도 즐겨찾기 여부와 즐겨찾기 개수가 올바르게 유지된다."""
    username, token = _register_user(client)
    article = _create_article(client, token)
    slug = cast(str, article["slug"])
    with test_session_factory() as session:
        user_id = _user_id(session, username)
        article_id = _article_id(session, slug)
    relationship_count = (
        select(func.count())
        .select_from(ArticleFavorite)
        .where(ArticleFavorite.article_id == article_id)
    )

    for method, expected_favorited, expected_count in (
        ("DELETE", False, 0),
        ("POST", True, 1),
        ("DELETE", False, 0),
    ):
        for _ in range(2):
            changed = client.request(
                method, f"/api/articles/{slug}/favorite", headers=_headers(token)
            )
            expected_article = article | {
                "favorited": expected_favorited,
                "favoritesCount": expected_count,
            }
            assert changed.status_code == 200
            assert changed.json() == {"article": expected_article}
            reread = client.get(f"/api/articles/{slug}", headers=_headers(token))
            assert reread.status_code == 200
            assert reread.json() == {"article": expected_article}
            with test_session_factory() as session:
                assert session.scalar(relationship_count) == expected_count
                assert (
                    session.get(ArticleFavorite, (user_id, article_id)) is not None
                ) is expected_favorited


def test_favorite_changes_preserve_other_user_and_article_relationships(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """즐겨찾기 추가·해제는 요청한 사용자의 대상 게시글에만 반영되며, 다른 즐겨찾기는 유지된다."""
    viewer, viewer_token = _register_user(client)
    other, other_token = _register_user(client)
    target = _create_article(client, other_token)
    second_target = _create_article(client, other_token)
    with test_session_factory() as session:
        viewer_id = _user_id(session, viewer)
        other_id = _user_id(session, other)
        target_id = _article_id(session, cast(str, target["slug"]))
        second_target_id = _article_id(session, cast(str, second_target["slug"]))
        session.add_all(
            [
                ArticleFavorite(user_id=other_id, article_id=target_id),
                ArticleFavorite(user_id=viewer_id, article_id=second_target_id),
            ]
        )
        session.commit()
    preserved_relationships = {(other_id, target_id), (viewer_id, second_target_id)}

    for method, expected_favorited, expected_count in (
        ("POST", True, 2),
        ("DELETE", False, 1),
    ):
        changed = client.request(
            method,
            f"/api/articles/{target['slug']}/favorite",
            headers=_headers(viewer_token),
        )
        assert changed.status_code == 200
        assert changed.json()["article"]["favorited"] is expected_favorited
        assert changed.json()["article"]["favoritesCount"] == expected_count
        expected_relationships = preserved_relationships | (
            {(viewer_id, target_id)} if expected_favorited else set()
        )
        with test_session_factory() as session:
            assert _relationships(session, [target_id, second_target_id]) == (
                expected_relationships
            )


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize("authorization", [None, "", "Token invalid"])
def test_rejected_favorite_auth_preserves_existing_relationships(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    method: str,
    authorization: str | None,
) -> None:
    """인증이 없거나 잘못된 인증 헤더를 보낸 즐겨찾기·해제 요청은 401로 거부하고 기존 즐겨찾기는 유지한다."""
    _, token = _register_user(client)
    article = _create_article(client, token)
    slug = cast(str, article["slug"])
    assert (
        client.post(
            f"/api/articles/{slug}/favorite", headers=_headers(token)
        ).status_code
        == 200
    )
    before = client.get(f"/api/articles/{slug}").json()
    with test_session_factory() as session:
        article_id = _article_id(session, slug)
        relationships_before = _relationships(session, [article_id])

    rejected = client.request(
        method,
        f"/api/articles/{slug}/favorite",
        headers={} if authorization is None else {"Authorization": authorization},
    )
    assert rejected.status_code == 401
    assert rejected.json() == {
        "errors": {"token": ["is missing" if not authorization else "is invalid"]}
    }
    assert client.get(f"/api/articles/{slug}").json() == before
    with test_session_factory() as session:
        assert _relationships(session, [article_id]) == relationships_before


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_missing_favorite_target_preserves_existing_relationships(
    client: TestClient, test_session_factory: sessionmaker[Session], method: str
) -> None:
    """존재하지 않는 게시글의 즐겨찾기·해제는 404로 거부하고 기존 게시글과 즐겨찾기는 유지한다."""
    _, token = _register_user(client)
    article = _create_article(client, token)
    slug = cast(str, article["slug"])
    assert (
        client.post(
            f"/api/articles/{slug}/favorite", headers=_headers(token)
        ).status_code
        == 200
    )
    before = client.get(f"/api/articles/{slug}").json()
    with test_session_factory() as session:
        article_id = _article_id(session, slug)
        relationships_before = _relationships(session, [article_id])

    rejected = client.request(
        method,
        f"/api/articles/unknown-{uuid4().hex}/favorite",
        headers=_headers(token),
    )
    assert rejected.status_code == 404
    assert rejected.json() == {"errors": {"article": ["not found"]}}
    assert client.get(f"/api/articles/{slug}").json() == before
    with test_session_factory() as session:
        assert _relationships(session, [article_id]) == relationships_before


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_old_slug_favorite_change_is_rejected_without_changing_relationships(
    client: TestClient, test_session_factory: sessionmaker[Session], method: str
) -> None:
    """제목 변경 전 주소는 조회에 사용할 수 있지만 즐겨찾기·해제는 404로 거부하고 현재 관계는 유지한다."""
    _, token = _register_user(client)
    article = _create_article(client, token)
    old_slug = cast(str, article["slug"])
    renamed = client.put(
        f"/api/articles/{old_slug}",
        headers=_headers(token),
        json={"article": {"title": f"Renamed {uuid4().hex}"}},
    )
    assert renamed.status_code == 200
    slug = renamed.json()["article"]["slug"]
    assert (
        client.post(
            f"/api/articles/{slug}/favorite", headers=_headers(token)
        ).status_code
        == 200
    )
    before = client.get(f"/api/articles/{slug}", headers=_headers(token))
    assert before.status_code == 200
    with test_session_factory() as session:
        article_id = _article_id(session, slug)
        relationships_before = _relationships(session, [article_id])

    rejected = client.request(
        method, f"/api/articles/{old_slug}/favorite", headers=_headers(token)
    )
    assert rejected.status_code == 404
    assert rejected.json() == {"errors": {"article": ["not found"]}}
    previous_read = client.get(f"/api/articles/{old_slug}", headers=_headers(token))
    assert previous_read.status_code == 200
    assert previous_read.json() == before.json()
    with test_session_factory() as session:
        assert _relationships(session, [article_id]) == relationships_before


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_favorite_database_failure_restores_relationships_and_preserves_content(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    """DB 저장 오류로 즐겨찾기·해제가 실패하면 기존 관계·건수·콘텐츠를 유지하고, 오류 제거 후 재시도는 성공한다."""
    client = server_error_client
    viewer, token = _register_user(client)
    other, other_token = _register_user(client)
    article = _create_article(client, other_token)
    second_article = _create_article(client, other_token)
    slug = cast(str, article["slug"])
    assert (
        client.post(
            f"/api/articles/{slug}/favorite", headers=_headers(other_token)
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/articles/{second_article['slug']}/favorite", headers=_headers(token)
        ).status_code
        == 200
    )
    if method == "DELETE":
        assert (
            client.post(
                f"/api/articles/{slug}/favorite", headers=_headers(token)
            ).status_code
            == 200
        )
    created_comment = client.post(
        f"/api/articles/{slug}/comments",
        headers=_headers(other_token),
        json={"comment": {"body": "Keep comment"}},
    )
    assert created_comment.status_code == 201
    article_before = client.get(f"/api/articles/{slug}", headers=_headers(token))
    assert article_before.status_code == 200
    comments_before = client.get(f"/api/articles/{slug}/comments")
    assert comments_before.status_code == 200
    with test_session_factory() as session:
        viewer_id = _user_id(session, viewer)
        other_id = _user_id(session, other)
        article_id = _article_id(session, slug)
        second_article_id = _article_id(session, cast(str, second_article["slug"]))
        relationships_before = _relationships(session, [article_id, second_article_id])
    database_error_seen = False
    changed_state_seen = False

    def fail_before_commit(session: Session) -> None:
        nonlocal database_error_seen, changed_state_seen
        session.flush()
        changed_state_seen = (
            session.get(ArticleFavorite, (viewer_id, article_id)) is not None
        ) == (method == "POST")
        try:
            session.execute(text("SELECT 1 / 0"))
        except DBAPIError:
            database_error_seen = True
            raise

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_before_commit)
        rejected = client.request(
            method, f"/api/articles/{slug}/favorite", headers=_headers(token)
        )
    assert rejected.status_code == 500
    assert database_error_seen and changed_state_seen
    reread = client.get(f"/api/articles/{slug}", headers=_headers(token))
    assert reread.status_code == 200
    assert reread.json() == article_before.json()
    comments_after = client.get(f"/api/articles/{slug}/comments")
    assert comments_after.status_code == 200
    assert comments_after.json() == comments_before.json()
    with test_session_factory() as session:
        assert _relationships(session, [article_id, second_article_id]) == (
            relationships_before
        )
        assert session.get(User, viewer_id) is not None
        assert session.get(User, other_id) is not None

    recovered = client.request(
        method, f"/api/articles/{slug}/favorite", headers=_headers(token)
    )
    expected_favorited = method == "POST"
    expected_count = 2 if expected_favorited else 1
    assert recovered.status_code == 200
    assert recovered.json()["article"]["favorited"] is expected_favorited
    assert recovered.json()["article"]["favoritesCount"] == expected_count
    reread = client.get(f"/api/articles/{slug}", headers=_headers(token))
    assert reread.status_code == 200
    assert reread.json() == recovered.json()
