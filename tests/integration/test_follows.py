from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.users.models import User, UserFollow


def _register_user(client: TestClient) -> tuple[str, str]:
    username = f"follow-{uuid4().hex}"
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


def _user_id(session: Session, username: str) -> int:
    user_id = session.scalar(select(User.id).where(User.username == username))
    assert user_id is not None
    return user_id


def _relationships(session: Session, follower_ids: list[int]) -> set[tuple[int, int]]:
    return {
        (follower_id, followed_id)
        for follower_id, followed_id in session.execute(
            select(UserFollow.follower_id, UserFollow.followed_id).where(
                UserFollow.follower_id.in_(follower_ids)
            )
        )
    }


def test_repeated_follow_and_unfollow_preserve_relationship_state(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """같은 사용자를 반복해서 팔로우해도 관계가 중복 저장되지 않고, 반복해서 해제해도 해제 상태를 유지한다."""
    viewer, viewer_token = _register_user(client)
    target, _ = _register_user(client)
    with test_session_factory() as session:
        viewer_id = _user_id(session, viewer)
        target_id = _user_id(session, target)
    relationship_count = (
        select(func.count())
        .select_from(UserFollow)
        .where(
            UserFollow.follower_id == viewer_id,
            UserFollow.followed_id == target_id,
        )
    )

    for method, expected_following, expected_count in (
        ("POST", True, 1),
        ("DELETE", False, 0),
    ):
        for _ in range(2):
            response = client.request(
                method, f"/api/profiles/{target}/follow", headers=_headers(viewer_token)
            )
            assert response.status_code == 200
            assert response.json()["profile"]["following"] is expected_following
            with test_session_factory() as session:
                assert session.scalar(relationship_count) == expected_count


def test_follow_changes_preserve_other_user_and_target_relationships(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """팔로우를 추가하거나 해제해도, 다른 사용자의 팔로우와 요청자가 다른 대상에게 맺은 팔로우는 유지된다."""
    viewer, viewer_token = _register_user(client)
    target, _ = _register_user(client)
    other, _ = _register_user(client)
    second_target, _ = _register_user(client)
    with test_session_factory() as session:
        viewer_id = _user_id(session, viewer)
        target_id = _user_id(session, target)
        other_id = _user_id(session, other)
        second_target_id = _user_id(session, second_target)
        session.add_all(
            [
                UserFollow(follower_id=other_id, followed_id=target_id),
                UserFollow(follower_id=viewer_id, followed_id=second_target_id),
            ]
        )
        session.commit()
    preserved_relationships = {
        (other_id, target_id),
        (viewer_id, second_target_id),
    }

    followed = client.post(
        f"/api/profiles/{target}/follow", headers=_headers(viewer_token)
    )
    assert followed.status_code == 200
    with test_session_factory() as session:
        assert _relationships(session, [viewer_id, other_id]) == (
            preserved_relationships | {(viewer_id, target_id)}
        )

    unfollowed = client.delete(
        f"/api/profiles/{target}/follow", headers=_headers(viewer_token)
    )
    assert unfollowed.status_code == 200
    with test_session_factory() as session:
        assert _relationships(session, [viewer_id, other_id]) == preserved_relationships


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize("authorization", [None, "", "Token invalid"])
def test_rejected_follow_auth_preserves_existing_relationships(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    method: str,
    authorization: str | None,
) -> None:
    """인증이 없거나 잘못된 인증 헤더를 보낸 팔로우·해제 요청은 401로 거부하고, 기존 팔로우 관계는 유지한다."""
    viewer, viewer_token = _register_user(client)
    target, _ = _register_user(client)
    assert (
        client.post(
            f"/api/profiles/{target}/follow", headers=_headers(viewer_token)
        ).status_code
        == 200
    )
    with test_session_factory() as session:
        viewer_id = _user_id(session, viewer)
        before = _relationships(session, [viewer_id])

    rejected = client.request(
        method,
        f"/api/profiles/{target}/follow",
        headers={} if authorization is None else {"Authorization": authorization},
    )

    assert rejected.status_code == 401
    assert rejected.json() == {
        "errors": {"token": ["is missing" if not authorization else "is invalid"]}
    }
    with test_session_factory() as session:
        assert _relationships(session, [viewer_id]) == before


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_self_follow_change_is_rejected_without_changing_other_relationships(
    client: TestClient, test_session_factory: sessionmaker[Session], method: str
) -> None:
    """자기 자신을 팔로우하거나 해제하려는 요청은 422로 거부하고, 다른 사용자를 팔로우한 기존 관계는 유지한다."""
    viewer, token = _register_user(client)
    target, _ = _register_user(client)
    assert (
        client.post(
            f"/api/profiles/{target}/follow", headers=_headers(token)
        ).status_code
        == 200
    )
    with test_session_factory() as session:
        viewer_id = _user_id(session, viewer)
        before = _relationships(session, [viewer_id])

    rejected = client.request(
        method, f"/api/profiles/{viewer}/follow", headers=_headers(token)
    )

    assert rejected.status_code == 422
    assert rejected.json() == {
        "errors": {"profile": ["can't follow or unfollow yourself"]}
    }
    self_profile = client.get(f"/api/profiles/{viewer}", headers=_headers(token))
    assert self_profile.status_code == 200
    assert self_profile.json()["profile"]["following"] is False
    with test_session_factory() as session:
        assert _relationships(session, [viewer_id]) == before


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_follow_database_failure_restores_relationships_and_preserves_content(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    """팔로우를 추가하거나 해제하는 중 DB 저장 오류가 발생하면 변경 전 상태를 유지한다.

    실패 응답은 500이며, 변경 전 팔로우 관계와 기존 게시글·댓글이 유지된다.
    오류가 사라진 뒤 같은 요청을 다시 보내면 성공하고, 새 조회에도 변경이 반영된다.
    """
    client = server_error_client
    viewer, token = _register_user(client)
    target, target_token = _register_user(client)
    other, other_token = _register_user(client)
    second_target, _ = _register_user(client)
    assert (
        client.post(
            f"/api/profiles/{target}/follow", headers=_headers(other_token)
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/profiles/{second_target}/follow", headers=_headers(token)
        ).status_code
        == 200
    )
    if method == "DELETE":
        assert (
            client.post(
                f"/api/profiles/{target}/follow", headers=_headers(token)
            ).status_code
            == 200
        )
    article_response = client.post(
        "/api/articles",
        headers=_headers(target_token),
        json={"article": {"title": "Existing", "description": "Keep", "body": "Keep"}},
    )
    assert article_response.status_code == 201
    article = article_response.json()["article"]
    slug = article["slug"]
    comment_response = client.post(
        f"/api/articles/{slug}/comments",
        headers=_headers(target_token),
        json={"comment": {"body": "Keep comment"}},
    )
    assert comment_response.status_code == 201
    with test_session_factory() as session:
        viewer_id = _user_id(session, viewer)
        target_id = _user_id(session, target)
        other_id = _user_id(session, other)
        before = _relationships(session, [viewer_id, other_id])
    database_error_seen = False
    changed_state_seen = False

    def fail_before_commit(session: Session) -> None:
        nonlocal database_error_seen, changed_state_seen
        session.flush()
        changed_state_seen = (
            session.get(UserFollow, (viewer_id, target_id)) is not None
        ) == (method == "POST")
        try:
            session.execute(text("SELECT 1 / 0"))
        except DBAPIError:
            database_error_seen = True
            raise

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_before_commit)
        rejected = client.request(
            method, f"/api/profiles/{target}/follow", headers=_headers(token)
        )

    assert rejected.status_code == 500
    assert database_error_seen and changed_state_seen
    profile = client.get(f"/api/profiles/{target}", headers=_headers(token))
    assert profile.status_code == 200
    assert profile.json()["profile"]["following"] is (method == "DELETE")
    with test_session_factory() as session:
        assert _relationships(session, [viewer_id, other_id]) == before
    assert client.get(f"/api/articles/{slug}").json() == {"article": article}
    assert client.get(f"/api/articles/{slug}/comments").json() == {
        "comments": [comment_response.json()["comment"]]
    }

    recovered = client.request(
        method, f"/api/profiles/{target}/follow", headers=_headers(token)
    )
    assert recovered.status_code == 200
    assert client.get(f"/api/profiles/{target}", headers=_headers(token)).json()[
        "profile"
    ]["following"] is (method == "POST")
