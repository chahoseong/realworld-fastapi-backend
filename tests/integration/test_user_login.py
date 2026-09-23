from uuid import uuid4

import jwt
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.security import JWT_ALGORITHM, hash_password
from app.users.models import User

LOGIN_USER_PATH = "/api/users/login"


def test_login_with_unknown_email_returns_invalid_credentials(
    client: TestClient,
) -> None:
    """존재하지 않는 이메일로 로그인하면 자격 증명 오류를 반환해야 한다."""
    # Arrange
    request_payload = {
        "user": {
            "email": f"unknown-{uuid4().hex}@example.com",
            "password": "password123",
        }
    }

    # Act
    response = client.post(LOGIN_USER_PATH, json=request_payload)

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"errors": {"credentials": ["invalid"]}}


def test_login_with_legacy_short_password_returns_user_jwt(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    test_jwt_secret_key: str,
) -> None:
    """기존의 짧은 비밀번호가 해시와 일치하면 해당 사용자의 JWT를 발급해야 한다."""
    # Arrange
    unique_value = uuid4().hex
    username = f"legacy-{unique_value}"
    email = f"legacy-{unique_value}@example.com"
    password = "short7"
    with test_session_factory() as session:
        with session.begin():
            user = User(
                username=username,
                email=email,
                password_hash=hash_password(password),
            )
            session.add(user)
            session.flush()
            user_id = user.id
    # Act
    response = client.post(
        LOGIN_USER_PATH,
        json={"user": {"email": email, "password": password}},
    )
    # Assert
    assert response.status_code == status.HTTP_200_OK
    response_user = response.json()["user"]
    assert response_user["username"] == username
    assert response_user["email"] == email
    assert response_user["bio"] is None
    assert response_user["image"] is None
    assert set(response_user) == {"username", "email", "bio", "image", "token"}

    claims = jwt.decode(
        response_user["token"],
        test_jwt_secret_key,
        algorithms=[JWT_ALGORITHM],
    )
    assert claims["sub"] == str(user_id)
