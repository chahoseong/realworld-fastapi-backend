from datetime import UTC, datetime

import jwt

from app.security import JWT_ALGORITHM, create_access_token


def test_create_access_token_contains_user_and_one_hour_lifetime() -> None:
    """발급 토큰에 사용자 ID와 발급 시각부터 1시간인 만료 시각을 담는다."""
    # Arrange
    user_id = 42
    secret_key = "unit-test-jwt-secret-key-at-least-32-bytes"
    earliest_issued_at = int(datetime.now(UTC).timestamp())

    # Act
    token = create_access_token(user_id, secret_key)
    latest_issued_at = int(datetime.now(UTC).timestamp())
    claims = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])

    # Assert
    assert claims["sub"] == str(user_id)
    assert type(claims["iat"]) is int
    assert type(claims["exp"]) is int
    assert earliest_issued_at <= claims["iat"] <= latest_issued_at
    assert claims["exp"] == claims["iat"] + 3600
