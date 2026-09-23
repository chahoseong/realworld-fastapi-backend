from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient


def _register_user(client: TestClient) -> tuple[str, str]:
    unique_value = uuid4().hex
    username = f"profile-{unique_value}"
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


def test_get_profile_exposes_only_public_fields_with_or_without_auth(
    client: TestClient,
) -> None:
    """비인증 요청과 다른 사용자의 인증 요청 모두 공개 프로필 필드만 반환한다."""
    # Arrange
    username, owner_token = _register_user(client)
    _, viewer_token = _register_user(client)
    update_response = client.put(
        "/api/user",
        headers={"Authorization": f"Token {owner_token}"},
        json={
            "user": {
                "bio": "Public bio",
                "image": "https://example.com/profile.png",
            }
        },
    )
    assert update_response.status_code == status.HTTP_200_OK

    # Act
    anonymous_response = client.get(f"/api/profiles/{username}")
    authenticated_response = client.get(
        f"/api/profiles/{username}",
        headers={"Authorization": f"Token {viewer_token}"},
    )

    # Assert
    expected_profile = {
        "profile": {
            "username": username,
            "bio": "Public bio",
            "image": "https://example.com/profile.png",
            "following": False,
        }
    }
    assert anonymous_response.status_code == status.HTTP_200_OK
    assert anonymous_response.json() == expected_profile
    assert authenticated_response.status_code == status.HTTP_200_OK
    assert authenticated_response.json() == expected_profile


@pytest.mark.parametrize("authorization", ["", "Token invalid"])
def test_get_profile_rejects_invalid_auth_before_missing_profile(
    client: TestClient,
    authorization: str,
) -> None:
    """잘못된 인증 헤더가 있으면 존재하지 않는 프로필도 404 대신 401로 거부한다."""
    # Arrange
    unknown_username = f"unknown-{uuid4().hex}"

    # Act
    response = client.get(
        f"/api/profiles/{unknown_username}",
        headers={"Authorization": authorization},
    )

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"errors": {"token": ["is invalid"]}}
