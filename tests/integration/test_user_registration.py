from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from httpx2 import Response

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
