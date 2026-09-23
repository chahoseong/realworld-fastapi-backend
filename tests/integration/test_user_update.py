from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.users.models import User

CURRENT_USER_PATH = "/api/user"


def _register_user(client: TestClient) -> tuple[str, str, str]:
    unique_value = uuid4().hex
    username = f"user-{unique_value}"
    email = f"user-{unique_value}@example.com"
    response = client.post(
        "/api/users",
        json={
            "user": {
                "username": username,
                "email": email,
                "password": "password123",
            }
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    return username, email, response.json()["user"]["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}"}


def _user_state(user: User) -> tuple[str, str, str, str | None, str | None]:
    return user.username, user.email, user.password_hash, user.bio, user.image


@pytest.mark.parametrize("field", ["username", "email"])
def test_update_user_changes_only_requested_field(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    field: str,
) -> None:
    """username 또는 email 하나만 변경하면 요청한 필드만 수정되고 나머지 필드는 유지된다."""
    # Arrange
    username, email, token = _register_user(client)
    other_username, other_email, other_token = _register_user(client)
    initial_response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {"bio": "About me", "image": "https://example.com/me.png"}},
    )
    assert initial_response.status_code == status.HTTP_200_OK
    updated_value = f"{username}-updated" if field == "username" else f"updated-{email}"
    with test_session_factory() as session:
        user_before = session.scalar(select(User).where(User.email == email))
        other_user_before = session.scalar(
            select(User).where(User.email == other_email)
        )
        assert user_before is not None and other_user_before is not None
        user_id = user_before.id
        password_hash_before = user_before.password_hash
        other_state_before = _user_state(other_user_before)

    # Act
    response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {field: updated_value}},
    )
    reread = client.get(CURRENT_USER_PATH, headers=_headers(token))
    other_reread = client.get(CURRENT_USER_PATH, headers=_headers(other_token))

    # Assert
    expected_user = {
        "username": username,
        "email": email,
        "token": token,
        "bio": "About me",
        "image": "https://example.com/me.png",
    }
    expected_user[field] = updated_value
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"user": expected_user}
    assert reread.json() == {"user": expected_user}
    assert other_reread.json() == {
        "user": {
            "username": other_username,
            "email": other_email,
            "token": other_token,
            "bio": None,
            "image": None,
        }
    }
    with test_session_factory() as session:
        stored_user = session.get(User, user_id)
        other_user = session.scalar(select(User).where(User.email == other_email))
    assert stored_user is not None
    assert stored_user.username == expected_user["username"]
    assert stored_user.email == expected_user["email"]
    assert stored_user.bio == "About me"
    assert stored_user.image == "https://example.com/me.png"
    assert stored_user.password_hash == password_hash_before
    assert other_user is not None
    assert _user_state(other_user) == other_state_before


def test_update_email_moves_login_to_new_email(client: TestClient) -> None:
    """email 변경 후 기존 비밀번호로 새 email 로그인은 성공하고 이전 email 로그인은 실패한다."""
    # Arrange
    _, email, token = _register_user(client)
    updated_email = f"updated-{email}"
    password = "password123"

    # Act
    update_response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {"email": updated_email}},
    )
    new_email_login = client.post(
        "/api/users/login",
        json={"user": {"email": updated_email, "password": password}},
    )
    old_email_login = client.post(
        "/api/users/login",
        json={"user": {"email": email, "password": password}},
    )

    # Assert
    assert update_response.status_code == status.HTTP_200_OK
    assert new_email_login.status_code == status.HTTP_200_OK
    assert new_email_login.json()["user"]["email"] == updated_email
    assert old_email_login.status_code == status.HTTP_401_UNAUTHORIZED
    assert old_email_login.json() == {"errors": {"credentials": ["invalid"]}}


@pytest.mark.parametrize("length", [8, 64])
def test_update_password_replaces_login_password(
    client: TestClient,
    length: int,
) -> None:
    """비밀번호만 변경하면 새 비밀번호로 로그인할 수 있고 기존 비밀번호로는 로그인할 수 없어야 한다."""
    # Arrange
    _, email, token = _register_user(client)
    updated_password = "a" * length

    # Act
    update_response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {"password": updated_password}},
    )
    old_password_login = client.post(
        "/api/users/login",
        json={"user": {"email": email, "password": "password123"}},
    )
    new_password_login = client.post(
        "/api/users/login",
        json={"user": {"email": email, "password": updated_password}},
    )

    # Assert
    assert update_response.status_code == status.HTTP_200_OK
    assert old_password_login.status_code == status.HTTP_401_UNAUTHORIZED
    assert old_password_login.json() == {"errors": {"credentials": ["invalid"]}}
    assert new_password_login.status_code == status.HTTP_200_OK
    assert new_password_login.json()["user"]["email"] == email


def test_update_password_does_not_revoke_existing_token(client: TestClient) -> None:
    """비밀번호를 변경해도 변경 전에 발급된 유효 토큰으로 본인 정보를 조회할 수 있어야 한다."""
    # Arrange
    _, email, token = _register_user(client)

    # Act
    update_response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {"password": "newpassword123"}},
    )
    current_user_response = client.get(CURRENT_USER_PATH, headers=_headers(token))

    # Assert
    assert update_response.status_code == status.HTTP_200_OK
    assert update_response.json()["user"]["token"] == token
    assert current_user_response.status_code == status.HTTP_200_OK
    assert current_user_response.json()["user"]["email"] == email
    assert current_user_response.json()["user"]["token"] == token


def test_update_user_rejects_empty_update_without_changing_account(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """빈 수정 요청은 거부되고 기존 계정 정보는 변경되지 않는다."""
    # Arrange
    _, email, token = _register_user(client)
    with test_session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        state_before = _user_state(user)

    # Act
    response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {}},
    )

    # Assert
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["errors"]
    with test_session_factory() as session:
        user_after = session.scalar(select(User).where(User.email == email))
    assert user_after is not None
    assert _user_state(user_after) == state_before


def test_update_user_rejects_too_short_password_without_changing_account(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """최소 길이보다 짧은 비밀번호 변경 요청은 거부되고 기존 계정 정보는 변경되지 않는다."""
    # Arrange
    username, email, token = _register_user(client)
    with test_session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        state_before = _user_state(user)

    # Act
    response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={
            "user": {
                "username": f"{username}-changed",
                "bio": "changed",
                "password": "a" * 7,
            }
        },
    )

    # Assert
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "password" in response.json()["errors"]
    with test_session_factory() as session:
        user_after = session.scalar(select(User).where(User.email == email))
    assert user_after is not None
    assert _user_state(user_after) == state_before


@pytest.mark.parametrize("duplicate_field", ["username", "email"])
def test_update_user_rejects_duplicate_username_or_email_without_partial_update(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    duplicate_field: str,
) -> None:
    """username 또는 email이 중복되면 수정 요청 전체가 거부되고 두 사용자 정보 모두 변경되지 않는다."""
    # Arrange
    _, email, token = _register_user(client)
    other_username, other_email, _ = _register_user(client)
    with test_session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        other_user = session.scalar(select(User).where(User.email == other_email))
        assert user is not None and other_user is not None
        state_before = _user_state(user)
        other_state_before = _user_state(other_user)
    duplicate_value = other_username if duplicate_field == "username" else other_email

    # Act
    response = client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {duplicate_field: duplicate_value, "bio": "should roll back"}},
    )

    # Assert
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json() == {"errors": {duplicate_field: ["has already been taken"]}}
    with test_session_factory() as session:
        user_after = session.scalar(select(User).where(User.email == email))
        other_user_after = session.scalar(select(User).where(User.email == other_email))
    assert user_after is not None and other_user_after is not None
    assert _user_state(user_after) == state_before
    assert _user_state(other_user_after) == other_state_before


def test_update_user_commit_failure_leaves_account_unchanged(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """커밋이 실패하면 수정된 내용은 저장되지 않고 기존 계정 정보가 유지된다."""
    # Arrange
    username, email, token = _register_user(server_error_client)
    _, other_email, _ = _register_user(server_error_client)
    with test_session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        other_user = session.scalar(select(User).where(User.email == other_email))
        assert user is not None and other_user is not None
        state_before = _user_state(user)
        other_state_before = _user_state(other_user)

    def fail_after_flush(session: Session) -> None:
        session.flush()
        raise RuntimeError("simulated commit failure")

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        failed_response = server_error_client.put(
            CURRENT_USER_PATH,
            headers=_headers(token),
            json={"user": {"username": f"{username}-changed", "bio": "changed"}},
        )

    # Assert
    assert failed_response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    with test_session_factory() as session:
        user_after_failure = session.scalar(select(User).where(User.email == email))
        other_user_after_failure = session.scalar(
            select(User).where(User.email == other_email)
        )
    assert user_after_failure is not None and other_user_after_failure is not None
    assert _user_state(user_after_failure) == state_before
    assert _user_state(other_user_after_failure) == other_state_before


def test_update_user_succeeds_after_transient_commit_failure(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """일시적인 커밋 실패 후 같은 프로세스에서 후속 수정 요청이 정상적으로 성공한다."""
    # Arrange
    _, email, token = _register_user(server_error_client)

    def fail_after_flush(session: Session) -> None:
        session.flush()
        raise RuntimeError("simulated commit failure")

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        failed_response = server_error_client.put(
            CURRENT_USER_PATH,
            headers=_headers(token),
            json={"user": {"bio": "failed"}},
        )
    recovery_response = server_error_client.put(
        CURRENT_USER_PATH,
        headers=_headers(token),
        json={"user": {"bio": "recovered"}},
    )

    # Assert
    assert failed_response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert recovery_response.status_code == status.HTTP_200_OK
    assert recovery_response.json()["user"]["bio"] == "recovered"
    with test_session_factory() as session:
        stored_user = session.scalar(select(User).where(User.email == email))
    assert stored_user is not None
    assert stored_user.bio == "recovered"
