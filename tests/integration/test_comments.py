from typing import cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.articles.models import Article, Tag
from app.comments.models import Comment
from app.users.models import User


def _register_user(client: TestClient) -> tuple[str, str]:
    username = f"comment-{uuid4().hex}"
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
    return username, cast(str, response.json()["user"]["token"])


def _create_article(
    client: TestClient, token: str, tags: list[str] | None = None
) -> dict[str, object]:
    article: dict[str, object] = {
        "title": f"Comment article {uuid4().hex}",
        "description": "For comments",
        "body": "Article body",
    }
    if tags is not None:
        article["tagList"] = tags
    response = client.post(
        "/api/articles",
        headers={"Authorization": f"Token {token}"},
        json={"article": article},
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, object], response.json()["article"])


def _create_comment(
    client: TestClient, token: str, slug: str, body: str
) -> dict[str, object]:
    response = client.post(
        f"/api/articles/{slug}/comments",
        headers={"Authorization": f"Token {token}"},
        json={"comment": {"body": body}},
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, object], response.json()["comment"])


def test_comment_on_another_users_article_is_public_and_scoped_to_article(
    client: TestClient,
) -> None:
    """다른 사용자도 댓글을 작성할 수 있고, 인증 없이 조회하면 해당 게시글의 댓글만 반환된다."""
    # Arrange
    _, owner_token = _register_user(client)
    commenter_name, commenter_token = _register_user(client)
    first = _create_article(client, owner_token)
    second = _create_article(client, owner_token)
    first_slug = cast(str, first["slug"])
    second_slug = cast(str, second["slug"])

    # Act
    initially_empty = client.get(f"/api/articles/{first_slug}/comments")
    created = _create_comment(client, commenter_token, first_slug, "A public comment")
    anonymous_list = client.get(f"/api/articles/{first_slug}/comments")
    other_article_list = client.get(f"/api/articles/{second_slug}/comments")

    # Assert
    assert initially_empty.status_code == status.HTTP_200_OK
    assert initially_empty.json() == {"comments": []}
    assert created["author"] == {
        "username": commenter_name,
        "bio": None,
        "image": None,
        "following": False,
    }
    assert anonymous_list.status_code == status.HTTP_200_OK
    assert anonymous_list.json() == {"comments": [created]}
    assert other_article_list.status_code == status.HTTP_200_OK
    assert other_article_list.json() == {"comments": []}


def test_article_rename_preserves_comment_reads_and_rejects_old_slug_creation(
    client: TestClient,
) -> None:
    """제목 변경 후 댓글은 새·이전 주소로 조회되지만 이전 주소로 작성할 수 없다."""
    # Arrange
    _, token = _register_user(client)
    article = _create_article(client, token)
    old_slug = cast(str, article["slug"])
    comment = _create_comment(client, token, old_slug, "Still attached")

    # Act
    renamed = client.put(
        f"/api/articles/{old_slug}",
        headers={"Authorization": f"Token {token}"},
        json={"article": {"title": f"Renamed {uuid4().hex}"}},
    )
    new_slug = cast(str, renamed.json()["article"]["slug"])
    current_list = client.get(f"/api/articles/{new_slug}/comments")
    previous_list = client.get(f"/api/articles/{old_slug}/comments")
    old_slug_creation = client.post(
        f"/api/articles/{old_slug}/comments",
        headers={"Authorization": f"Token {token}"},
        json={"comment": {"body": "Wrong write address"}},
    )

    # Assert
    assert renamed.status_code == status.HTTP_200_OK
    assert new_slug != old_slug
    assert current_list.status_code == status.HTTP_200_OK
    assert current_list.json() == {"comments": [comment]}
    assert previous_list.status_code == status.HTTP_200_OK
    assert previous_list.json() == {"comments": [comment]}
    assert old_slug_creation.status_code == status.HTTP_404_NOT_FOUND
    assert old_slug_creation.json() == {"errors": {"article": ["not found"]}}


def test_invalid_token_is_rejected_when_listing_comments(
    client: TestClient,
) -> None:
    """익명 조회는 허용해도 잘못된 인증 헤더가 있으면 댓글 목록을 반환하지 않는다."""
    # Arrange
    _, token = _register_user(client)
    article = _create_article(client, token)

    # Act
    response = client.get(
        f"/api/articles/{article['slug']}/comments",
        headers={"Authorization": "Token invalid"},
    )

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"errors": {"token": ["is invalid"]}}


def test_only_comment_author_can_delete_their_comment_on_another_users_article(
    client: TestClient,
) -> None:
    """게시글 작성자도 타인의 댓글은 삭제할 수 없고 댓글 작성자는 삭제할 수 있다."""
    # Arrange
    _, article_author_token = _register_user(client)
    _, comment_author_token = _register_user(client)
    article = _create_article(client, article_author_token)
    slug = cast(str, article["slug"])
    comment = _create_comment(client, comment_author_token, slug, "Own comment")
    comment_url = f"/api/articles/{slug}/comments/{comment['id']}"

    # Act
    forbidden = client.delete(
        comment_url,
        headers={"Authorization": f"Token {article_author_token}"},
    )
    after_forbidden = client.get(f"/api/articles/{slug}/comments")

    # Assert
    assert forbidden.status_code == status.HTTP_403_FORBIDDEN
    assert forbidden.json() == {"errors": {"comment": ["forbidden"]}}
    assert after_forbidden.json() == {"comments": [comment]}

    # Act
    deleted = client.delete(
        comment_url,
        headers={"Authorization": f"Token {comment_author_token}"},
    )
    after_deletion = client.get(f"/api/articles/{slug}/comments")
    article_read = client.get(f"/api/articles/{slug}")

    # Assert
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert after_deletion.json() == {"comments": []}
    assert article_read.status_code == status.HTTP_200_OK


def test_comment_cannot_be_deleted_through_another_articles_slug(
    client: TestClient,
) -> None:
    """다른 게시글의 slug와 댓글 ID를 조합해도 댓글이 삭제되지 않는다."""
    # Arrange
    _, token = _register_user(client)
    first_article = _create_article(client, token)
    second_article = _create_article(client, token)
    first_slug = cast(str, first_article["slug"])
    second_slug = cast(str, second_article["slug"])
    comment = _create_comment(client, token, first_slug, "First article comment")

    # Act
    rejected = client.delete(
        f"/api/articles/{second_slug}/comments/{comment['id']}",
        headers={"Authorization": f"Token {token}"},
    )
    first_comments = client.get(f"/api/articles/{first_slug}/comments")
    second_comments = client.get(f"/api/articles/{second_slug}/comments")

    # Assert
    assert rejected.status_code == status.HTTP_404_NOT_FOUND
    assert rejected.json() == {"errors": {"comment": ["not found"]}}
    assert first_comments.json() == {"comments": [comment]}
    assert second_comments.json() == {"comments": []}


def test_deleting_article_removes_its_comments_without_affecting_other_data(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """게시글 삭제는 그 글의 댓글만 제거하고 다른 글·댓글·공유 태그를 유지한다."""
    # Arrange
    owner_name, owner_token = _register_user(client)
    commenter_name, commenter_token = _register_user(client)
    shared_tag = f"shared-{uuid4().hex}"
    deleted_article = _create_article(client, owner_token, [shared_tag])
    kept_article = _create_article(client, owner_token, [shared_tag])
    deleted_slug = cast(str, deleted_article["slug"])
    kept_slug = cast(str, kept_article["slug"])
    deleted_comment = _create_comment(
        client, commenter_token, deleted_slug, "On deleted article"
    )
    kept_comment = _create_comment(
        client, commenter_token, kept_slug, "On kept article"
    )

    # Act
    deleted = client.delete(
        f"/api/articles/{deleted_slug}",
        headers={"Authorization": f"Token {owner_token}"},
    )
    kept_article_read = client.get(f"/api/articles/{kept_slug}")
    kept_comments = client.get(f"/api/articles/{kept_slug}/comments")
    tags = client.get("/api/tags")
    with test_session_factory() as session:
        removed_comment = session.get(Comment, deleted_comment["id"])
        stored_comment = session.get(Comment, kept_comment["id"])
        stored_article = session.scalar(
            select(Article).where(Article.slug == kept_slug)
        )
        owner = session.scalar(select(User).where(User.username == owner_name))
        commenter = session.scalar(select(User).where(User.username == commenter_name))
        stored_tag = session.scalar(select(Tag).where(Tag.name == shared_tag))

    # Assert
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert kept_article_read.status_code == status.HTTP_200_OK
    assert kept_article_read.json()["article"] == kept_article
    assert kept_comments.status_code == status.HTTP_200_OK
    assert kept_comments.json() == {"comments": [kept_comment]}
    assert tags.status_code == status.HTTP_200_OK
    assert shared_tag in tags.json()["tags"]
    assert removed_comment is None
    assert stored_article is not None
    assert stored_comment is not None and stored_comment.article_id == stored_article.id
    assert owner is not None and commenter is not None and stored_tag is not None


def test_comment_creation_database_failure_leaves_no_comment_and_preserves_article(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB 오류로 댓글 저장이 실패하면 댓글은 남지 않고 게시글은 유지된다."""
    # Arrange
    _, owner_token = _register_user(server_error_client)
    _, commenter_token = _register_user(server_error_client)
    article = _create_article(server_error_client, owner_token)
    slug = cast(str, article["slug"])
    rejected_body = f"rollback-{uuid4().hex}"
    database_error_seen = False

    def fail_after_flush(session: Session) -> None:
        nonlocal database_error_seen
        session.flush()
        try:
            session.execute(text("SELECT 1 / 0"))
        except DBAPIError:
            database_error_seen = True
            raise

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        rejected = server_error_client.post(
            f"/api/articles/{slug}/comments",
            headers={"Authorization": f"Token {commenter_token}"},
            json={"comment": {"body": rejected_body}},
        )
    reread_article = server_error_client.get(f"/api/articles/{slug}")
    reread_comments = server_error_client.get(f"/api/articles/{slug}/comments")
    with test_session_factory() as session:
        stored_article = session.scalar(select(Article).where(Article.slug == slug))
        stored_comment = session.scalar(
            select(Comment).where(Comment.body == rejected_body)
        )

    # Assert
    assert rejected.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert database_error_seen
    assert reread_article.status_code == status.HTTP_200_OK
    assert reread_article.json()["article"] == article
    assert reread_comments.status_code == status.HTTP_200_OK
    assert reread_comments.json() == {"comments": []}
    assert stored_article is not None
    assert stored_comment is None


def test_comment_delete_database_failure_preserves_comment_and_article(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB 오류로 댓글 삭제에 실패하면 댓글과 게시글이 유지된다."""
    # Arrange
    _, token = _register_user(server_error_client)
    article = _create_article(server_error_client, token)
    slug = cast(str, article["slug"])
    comment = _create_comment(server_error_client, token, slug, "Keep comment")
    database_error_seen = False

    def fail_after_flush(session: Session) -> None:
        nonlocal database_error_seen
        session.flush()
        try:
            session.execute(text("SELECT 1 / 0"))
        except DBAPIError:
            database_error_seen = True
            raise

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        rejected = server_error_client.delete(
            f"/api/articles/{slug}/comments/{comment['id']}",
            headers={"Authorization": f"Token {token}"},
        )
    reread_article = server_error_client.get(f"/api/articles/{slug}")
    reread_comments = server_error_client.get(f"/api/articles/{slug}/comments")
    with test_session_factory() as session:
        stored_comment = session.get(Comment, comment["id"])

    # Assert
    assert rejected.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert database_error_seen
    assert reread_article.status_code == status.HTTP_200_OK
    assert reread_article.json()["article"] == article
    assert reread_comments.status_code == status.HTTP_200_OK
    assert reread_comments.json() == {"comments": [comment]}
    assert stored_comment is not None


def test_article_delete_database_failure_restores_comment_and_tag(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB 오류로 게시글 삭제에 실패하면 글·댓글·태그가 함께 유지된다."""
    # Arrange
    _, owner_token = _register_user(server_error_client)
    _, commenter_token = _register_user(server_error_client)
    tag = f"rollback-{uuid4().hex}"
    article = _create_article(server_error_client, owner_token, [tag])
    slug = cast(str, article["slug"])
    comment = _create_comment(server_error_client, commenter_token, slug, "Keep me")
    database_error_seen = False

    def fail_after_flush(session: Session) -> None:
        nonlocal database_error_seen
        session.flush()
        try:
            session.execute(text("SELECT 1 / 0"))
        except DBAPIError:
            database_error_seen = True
            raise

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        rejected = server_error_client.delete(
            f"/api/articles/{slug}",
            headers={"Authorization": f"Token {owner_token}"},
        )
    reread_article = server_error_client.get(f"/api/articles/{slug}")
    reread_comments = server_error_client.get(f"/api/articles/{slug}/comments")
    tags = server_error_client.get("/api/tags")
    with test_session_factory() as session:
        stored_comment = session.get(Comment, comment["id"])
        stored_tag = session.scalar(select(Tag).where(Tag.name == tag))

    # Assert
    assert rejected.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert database_error_seen
    assert reread_article.status_code == status.HTTP_200_OK
    assert reread_article.json()["article"] == article
    assert reread_comments.status_code == status.HTTP_200_OK
    assert reread_comments.json() == {"comments": [comment]}
    assert tags.status_code == status.HTTP_200_OK
    assert tag in tags.json()["tags"]
    assert stored_comment is not None and stored_tag is not None
