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


def test_profile_responses_expose_only_public_fields_and_viewer_following(
    client: TestClient,
) -> None:
    """조회·팔로우·해제는 공개 필드만 반환하고 following은 조회자와 관계 방향에 따른다."""
    # Arrange
    username, owner_token = _register_user(client)
    viewer_username, viewer_token = _register_user(client)
    _, other_token = _register_user(client)
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

    expected_profile = {
        "username": username,
        "bio": "Public bio",
        "image": "https://example.com/profile.png",
        "following": False,
    }

    # Act / Assert: 팔로우 응답과 새 조회는 공개 필드 및 조회자별 관계를 반환한다.
    followed = client.post(
        f"/api/profiles/{username}/follow",
        headers={"Authorization": f"Token {viewer_token}"},
    )
    assert followed.status_code == status.HTTP_200_OK
    assert followed.json() == {"profile": expected_profile | {"following": True}}
    for headers, following in (
        ({"Authorization": f"Token {viewer_token}"}, True),
        ({"Authorization": f"Token {other_token}"}, False),
        ({}, False),
    ):
        response = client.get(f"/api/profiles/{username}", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "profile": expected_profile | {"following": following}
        }
    reverse = client.get(
        f"/api/profiles/{viewer_username}",
        headers={"Authorization": f"Token {owner_token}"},
    )
    assert reverse.status_code == status.HTTP_200_OK
    assert reverse.json()["profile"]["following"] is False

    # Act / Assert: 해제 응답과 새 조회도 공개 필드를 유지하고 관계 해제를 반영한다.
    unfollowed = client.delete(
        f"/api/profiles/{username}/follow",
        headers={"Authorization": f"Token {viewer_token}"},
    )
    assert unfollowed.status_code == status.HTTP_200_OK
    assert unfollowed.json() == {"profile": expected_profile}
    reread = client.get(
        f"/api/profiles/{username}",
        headers={"Authorization": f"Token {viewer_token}"},
    )
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json() == {"profile": expected_profile}


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
