from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.security import JWT_ALGORITHM, verify_password
from app.users.models import User

REGISTER_USER_PATH = "/api/users"

UserInput = dict[str, str | None]
RegistrationPayload = dict[str, UserInput]


def _registration_payload(**overrides: str | None) -> RegistrationPayload:
    unique_value = uuid4().hex
    user: UserInput = {
        "username": f"user-{unique_value}",
        "email": f"user-{unique_value}@example.com",
        "password": "password123",
    }
    user.update(overrides)
    return {"user": user}


def _assert_validation_error_response(response: Response) -> dict[str, list[str]]:
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    body = response.json()
    assert isinstance(body, dict)
    assert set(body) == {"errors"}

    errors = body["errors"]
    assert isinstance(errors, dict)
    assert errors
    assert all(isinstance(field, str) for field in errors)
    assert all(
        isinstance(messages, list)
        and messages
        and all(isinstance(message, str) for message in messages)
        for messages in errors.values()
    )
    return errors


def _user_count(session: Session) -> int:
    count = session.scalar(select(func.count()).select_from(User))
    assert count is not None
    return count


def _user_state(
    user: User,
) -> tuple[int, str, str, str, str | None, str | None]:
    return (
        user.id,
        user.username,
        user.email,
        user.password_hash,
        user.bio,
        user.image,
    )


def test_register_user_without_body_returns_422_errors(
    client: TestClient,
) -> None:
    """요청 body가 없을 때 422 오류를 반환해야 한다."""
    # Arrange
    request_path = REGISTER_USER_PATH

    # Act
    response = client.post(request_path)

    # Assert
    _assert_validation_error_response(response)


def test_register_user_without_user_returns_422_errors(
    client: TestClient,
) -> None:
    """최상위 user 객체가 없을 때 422 오류를 반환해야 한다."""
    # Arrange
    request_payload: dict[str, object] = {}

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    _assert_validation_error_response(response)


@pytest.mark.parametrize(
    "field",
    ["username", "email", "password"],
)
def test_register_user_with_missing_field_returns_422_errors(
    client: TestClient,
    field: str,
) -> None:
    """필수 사용자 필드가 누락되면 422 오류를 반환해야 한다."""
    # Arrange
    request_payload = _registration_payload()
    request_payload["user"].pop(field)

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    _assert_validation_error_response(response)


@pytest.mark.parametrize(
    "field",
    ["username", "email", "password"],
)
def test_register_user_with_null_field_returns_422_errors(
    client: TestClient,
    field: str,
) -> None:
    """필수 사용자 필드가 null이면 422 오류를 반환해야 한다."""
    # Arrange
    request_payload = _registration_payload()
    request_payload["user"][field] = None

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    _assert_validation_error_response(response)


def test_register_user_with_invalid_email_returns_422_errors(
    client: TestClient,
) -> None:
    """email 형식이 유효하지 않으면 email 필드의 422 오류를 반환해야 한다."""
    # Arrange
    request_payload = _registration_payload(email="not-an-email")

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    errors = _assert_validation_error_response(response)
    assert "email" in errors


@pytest.mark.parametrize(
    "field",
    ["username", "email", "password"],
)
def test_register_user_with_whitespace_only_field_returns_blank_error(
    client: TestClient,
    field: str,
) -> None:
    """사용자 필드가 공백 문자로만 구성되면 blank 오류를 반환해야 한다."""
    # Arrange
    request_payload = _registration_payload()
    request_payload["user"][field] = " \t "

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    errors = _assert_validation_error_response(response)
    assert errors[field] == ["can't be blank"]


def test_register_user_with_short_password_returns_201(
    client: TestClient,
) -> None:
    """비어 있지 않은 짧은 password에 별도 길이 정책을 적용하지 않아야 한다."""
    # Arrange
    request_payload = _registration_payload(password="x")

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    assert response.status_code == status.HTTP_201_CREATED


def test_register_user_does_not_trim_username(
    client: TestClient,
) -> None:
    """공백만 있는 값이 아닌 username은 앞뒤 공백을 제거하지 않아야 한다."""
    # Arrange
    username = f" user-{uuid4().hex} "
    request_payload = _registration_payload(username=username)

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["user"]["username"] == username


def test_register_user_normalizes_email(
    client: TestClient,
) -> None:
    """EmailStr이 email의 주변 공백과 도메인 대소문자를 정규화해야 한다."""
    # Arrange
    unique_value = uuid4().hex
    request_payload = _registration_payload(
        email=f" User-{unique_value}@EXAMPLE.COM ",
    )
    expected_email = f"User-{unique_value}@example.com"

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["user"]["email"] == expected_email


def test_register_user_persists_user_in_database(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """등록 요청이 끝난 후 사용자 정보가 데이터베이스에 저장되어 있어야 한다."""
    # Arrange
    request_payload = _registration_payload()
    expected_user = request_payload["user"]

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    assert response.status_code == status.HTTP_201_CREATED
    with test_session_factory() as session:
        stored_user = session.scalar(
            select(User).where(User.email == expected_user["email"])
        )

    assert stored_user is not None
    assert stored_user.username == expected_user["username"]
    assert stored_user.email == expected_user["email"]
    assert stored_user.bio is None
    assert stored_user.image is None


def test_registering_users_with_same_password_stores_different_hashes(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """같은 비밀번호로 사용자를 등록해도 서로 다른 해시가 저장되어야 한다."""
    # Arrange
    password = "shared-password"
    first_payload = _registration_payload(password=password)
    second_payload = _registration_payload(password=password)

    # Act
    first_response = client.post(REGISTER_USER_PATH, json=first_payload)
    second_response = client.post(REGISTER_USER_PATH, json=second_payload)

    # Assert
    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_201_CREATED
    with test_session_factory() as session:
        first_user = session.scalar(
            select(User).where(User.email == first_payload["user"]["email"])
        )
        second_user = session.scalar(
            select(User).where(User.email == second_payload["user"]["email"])
        )

    assert first_user is not None
    assert second_user is not None
    assert first_user.password_hash != second_user.password_hash


def test_register_user_stores_verifiable_password_hash(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """등록한 비밀번호는 원문이 아닌 검증 가능한 해시로 저장되어야 한다."""
    # Arrange
    password = "password-to-verify"
    request_payload = _registration_payload(password=password)

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    assert response.status_code == status.HTTP_201_CREATED
    with test_session_factory() as session:
        stored_user = session.scalar(
            select(User).where(User.email == request_payload["user"]["email"])
        )

    assert stored_user is not None
    assert stored_user.password_hash != password
    assert verify_password(password, stored_user.password_hash)
    assert not verify_password("different-password", stored_user.password_hash)


def test_register_user_does_not_expose_password_fields(
    client: TestClient,
) -> None:
    """등록 응답에 평문 비밀번호와 비밀번호 해시를 포함하지 않아야 한다."""
    # Arrange
    request_payload = _registration_payload()

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)

    # Assert
    assert response.status_code == status.HTTP_201_CREATED
    response_user = response.json()["user"]
    assert "password" not in response_user
    assert "password_hash" not in response_user


def test_register_user_returns_jwt_with_sub_and_one_hour_expiry(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    test_jwt_secret_key: str,
) -> None:
    """회원가입 JWT가 저장된 사용자를 식별하고 발급 1시간 후 만료되어야 한다."""
    # Arrange
    request_payload = _registration_payload()
    earliest_issued_at = int(datetime.now(UTC).timestamp())

    # Act
    response = client.post(REGISTER_USER_PATH, json=request_payload)
    latest_issued_at = int(datetime.now(UTC).timestamp())

    # Assert
    assert response.status_code == status.HTTP_201_CREATED
    token = response.json()["user"]["token"]
    claims = jwt.decode(
        token,
        test_jwt_secret_key,
        algorithms=[JWT_ALGORITHM],
    )
    with test_session_factory() as session:
        stored_user = session.scalar(
            select(User).where(User.email == request_payload["user"]["email"])
        )

    assert stored_user is not None
    assert claims["sub"] == str(stored_user.id)
    assert type(claims["iat"]) is int
    assert type(claims["exp"]) is int
    assert earliest_issued_at <= claims["iat"] <= latest_issued_at
    assert claims["exp"] == claims["iat"] + 3600


def test_register_user_without_password_does_not_change_database(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """password가 누락된 요청은 사용자 데이터베이스를 변경하지 않아야 한다."""
    # Arrange
    existing_payload = _registration_payload()
    invalid_payload = _registration_payload()
    invalid_payload["user"].pop("password")
    existing_response = client.post(REGISTER_USER_PATH, json=existing_payload)
    assert existing_response.status_code == status.HTTP_201_CREATED

    with test_session_factory() as session:
        existing_user = session.scalar(
            select(User).where(User.email == existing_payload["user"]["email"])
        )
        assert existing_user is not None
        user_count_before = _user_count(session)
        existing_user_state_before = _user_state(existing_user)

    # Act
    response = client.post(REGISTER_USER_PATH, json=invalid_payload)

    # Assert
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    with test_session_factory() as session:
        existing_user_after = session.get(User, existing_user_state_before[0])
        invalid_user = session.scalar(
            select(User).where(User.email == invalid_payload["user"]["email"])
        )
        user_count_after = _user_count(session)

    assert existing_user_after is not None
    assert _user_state(existing_user_after) == existing_user_state_before
    assert invalid_user is None
    assert user_count_after == user_count_before


@pytest.mark.parametrize("duplicate_field", ["username", "email"])
def test_register_user_with_duplicate_username_or_email_does_not_change_database(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    duplicate_field: str,
) -> None:
    """username이나 email 중복 요청은 사용자 데이터베이스를 변경하지 않아야 한다."""
    # Arrange
    existing_payload = _registration_payload()
    duplicate_payload = _registration_payload(password="different-password")
    duplicate_payload["user"][duplicate_field] = existing_payload["user"][
        duplicate_field
    ]
    existing_response = client.post(REGISTER_USER_PATH, json=existing_payload)
    assert existing_response.status_code == status.HTTP_201_CREATED

    with test_session_factory() as session:
        existing_user = session.scalar(
            select(User).where(User.email == existing_payload["user"]["email"])
        )
        assert existing_user is not None
        user_count_before = _user_count(session)
        existing_user_state_before = _user_state(existing_user)

    # Act
    response = client.post(REGISTER_USER_PATH, json=duplicate_payload)

    # Assert
    assert response.status_code == status.HTTP_409_CONFLICT
    with test_session_factory() as session:
        existing_user_after = session.get(User, existing_user_state_before[0])
        user_count_after = _user_count(session)
        if duplicate_field == "username":
            unexpected_user = session.scalar(
                select(User).where(User.email == duplicate_payload["user"]["email"])
            )
        else:
            unexpected_user = session.scalar(
                select(User).where(
                    User.username == duplicate_payload["user"]["username"]
                )
            )

    assert existing_user_after is not None
    assert _user_state(existing_user_after) == existing_user_state_before
    assert unexpected_user is None
    assert user_count_after == user_count_before


def test_register_user_returns_500_without_persisting_user_when_database_write_fails(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """데이터베이스 쓰기 실패를 성공으로 응답하거나 사용자를 남기지 않아야 한다."""
    # Arrange
    request_payload = _registration_payload()
    with test_session_factory() as session:
        user_count_before = _user_count(session)

    # Act
    with monkeypatch.context() as patch:
        patch.setattr("app.users.router.hash_password", lambda _: None)
        response = server_error_client.post(
            REGISTER_USER_PATH,
            json=request_payload,
        )

    # Assert
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    with test_session_factory() as session:
        persisted_user = session.scalar(
            select(User).where(User.email == request_payload["user"]["email"])
        )
        user_count_after = _user_count(session)

    assert persisted_user is None
    assert user_count_after == user_count_before


def test_register_user_succeeds_after_previous_database_write_failure(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이전 데이터베이스 쓰기 실패가 해소되면 후속 가입 요청은 성공해야 한다."""
    # Arrange
    request_payload = _registration_payload()
    with test_session_factory() as session:
        user_count_before = _user_count(session)

    # Act
    with monkeypatch.context() as patch:
        patch.setattr("app.users.router.hash_password", lambda _: None)
        failed_response = server_error_client.post(
            REGISTER_USER_PATH,
            json=request_payload,
        )
    successful_response = server_error_client.post(
        REGISTER_USER_PATH,
        json=request_payload,
    )

    # Assert
    assert failed_response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert successful_response.status_code == status.HTTP_201_CREATED
    with test_session_factory() as session:
        persisted_users = session.scalars(
            select(User).where(User.email == request_payload["user"]["email"])
        ).all()
        user_count_after = _user_count(session)

    assert len(persisted_users) == 1
    assert user_count_after == user_count_before + 1
