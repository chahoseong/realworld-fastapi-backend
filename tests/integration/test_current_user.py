from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.security import JWT_ALGORITHM
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


def test_get_current_user_returns_token_owner_without_refresh(
    client: TestClient,
) -> None:
    """가입·로그인 토큰이 각 계정만 조회하고 요청 토큰을 그대로 반환해야 한다."""
    # Arrange
    first_username, first_email, registration_token = _register_user(client)
    second_username, second_email, second_token = _register_user(client)
    login_response = client.post(
        "/api/users/login",
        json={"user": {"email": first_email, "password": "password123"}},
    )
    assert login_response.status_code == status.HTTP_200_OK
    login_token = login_response.json()["user"]["token"]

    # Act
    registration_result = client.get(
        CURRENT_USER_PATH,
        headers={"Authorization": f"Token {registration_token}"},
    )
    login_result = client.get(
        CURRENT_USER_PATH,
        headers={"Authorization": f"Token {login_token}"},
    )
    second_result = client.get(
        CURRENT_USER_PATH,
        headers={"Authorization": f"Token {second_token}"},
    )

    # Assert
    for response, username, email, token in (
        (registration_result, first_username, first_email, registration_token),
        (login_result, first_username, first_email, login_token),
        (second_result, second_username, second_email, second_token),
    ):
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "user": {
                "username": username,
                "email": email,
                "token": token,
                "bio": None,
                "image": None,
            }
        }


def test_get_current_user_without_token_returns_missing_error(
    client: TestClient,
) -> None:
    """인증 헤더가 없으면 현재 사용자 정보를 반환하지 않아야 한다."""
    # Arrange
    request_path = CURRENT_USER_PATH

    # Act
    response = client.get(request_path)

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"errors": {"token": ["is missing"]}}


@pytest.mark.parametrize(
    "token_case",
    ["wrong_scheme", "tampered", "unknown_user", "invalid_subject"],
)
def test_get_current_user_rejects_invalid_token(
    client: TestClient,
    test_jwt_secret_key: str,
    token_case: str,
) -> None:
    """형식·서명·사용자 식별이 잘못된 토큰은 개인 정보에 접근하지 못해야 한다."""
    # Arrange
    _, _, valid_token = _register_user(client)
    if token_case == "wrong_scheme":
        authorization = f"Bearer {valid_token}"
    elif token_case == "tampered":
        header, payload, signature = valid_token.split(".")
        first_character = "A" if signature[0] != "A" else "B"
        authorization = f"Token {header}.{payload}.{first_character}{signature[1:]}"
    else:
        subject = "2147483647" if token_case == "unknown_user" else "invalid-id"
        token = jwt.encode(
            {"sub": subject, "exp": datetime.now(UTC) + timedelta(hours=1)},
            test_jwt_secret_key,
            algorithm=JWT_ALGORITHM,
        )
        authorization = f"Token {token}"

    # Act
    response = client.get(
        CURRENT_USER_PATH,
        headers={"Authorization": authorization},
    )

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"errors": {"token": ["is invalid"]}}


@pytest.mark.parametrize("token_state", ["expired", "at_expiry", "missing_exp"])
def test_get_current_user_rejects_old_token_and_allows_relogin(
    client: TestClient,
    test_jwt_secret_key: str,
    test_session_factory: sessionmaker[Session],
    token_state: str,
) -> None:
    """만료·무기한 토큰은 거부하고 기존 계정의 재로그인으로 접근을 회복해야 한다."""
    # Arrange
    username, email, registration_token = _register_user(client)
    subject = jwt.decode(
        registration_token,
        test_jwt_secret_key,
        algorithms=[JWT_ALGORITHM],
    )["sub"]
    with test_session_factory() as session:
        user_before = session.get(User, int(subject))
        assert user_before is not None
        password_hash_before = user_before.password_hash

    claims = {"sub": subject}
    if token_state == "expired":
        claims["exp"] = int(datetime.now(UTC).timestamp()) - 1
    elif token_state == "at_expiry":
        claims["exp"] = int(datetime.now(UTC).timestamp())
    old_token = jwt.encode(claims, test_jwt_secret_key, algorithm=JWT_ALGORITHM)

    # Act
    denied_response = client.get(
        CURRENT_USER_PATH,
        headers={"Authorization": f"Token {old_token}"},
    )
    login_response = client.post(
        "/api/users/login",
        json={"user": {"email": email, "password": "password123"}},
    )
    assert login_response.status_code == status.HTTP_200_OK
    new_token = login_response.json()["user"]["token"]
    recovered_response = client.get(
        CURRENT_USER_PATH,
        headers={"Authorization": f"Token {new_token}"},
    )

    # Assert
    assert denied_response.status_code == status.HTTP_401_UNAUTHORIZED
    assert denied_response.json() == {"errors": {"token": ["is invalid"]}}
    assert recovered_response.status_code == status.HTTP_200_OK
    assert recovered_response.json()["user"] == {
        "username": username,
        "email": email,
        "token": new_token,
        "bio": None,
        "image": None,
    }
    with test_session_factory() as session:
        user_after = session.get(User, int(subject))
        assert user_after is not None
        assert user_after.password_hash == password_hash_before
