import pytest
from pydantic import ValidationError

from app.users.schemas import UpdateUser


def test_update_user_rejects_whitespace_only_username() -> None:
    """공백 문자만 포함한 사용자 이름으로는 계정을 수정할 수 없다."""
    # Arrange
    payload = {"username": " \t "}

    # Act
    with pytest.raises(ValidationError) as exc_info:
        UpdateUser.model_validate(payload)

    # Assert
    errors = exc_info.value.errors()
    assert [(error["loc"], error["msg"]) for error in errors] == [
        (("username",), "can't be blank")
    ]


def test_update_user_rejects_whitespace_only_password_at_minimum_length() -> None:
    """최소 길이를 채운 공백 비밀번호도 수정 값으로 허용하지 않는다."""
    # Arrange
    payload = {"password": " " * 8}

    # Act
    with pytest.raises(ValidationError) as exc_info:
        UpdateUser.model_validate(payload)

    # Assert
    errors = exc_info.value.errors()
    assert [(error["loc"], error["msg"]) for error in errors] == [
        (("password",), "can't be blank")
    ]
