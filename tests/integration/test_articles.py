from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from typing import cast
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.articles.models import Article, ArticleTag, Tag
from app.users.models import User


def _register_user(client: TestClient) -> tuple[str, str]:
    username = f"article-{uuid4().hex}"
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


def _article_input(title: str, tags: list[str] | None = None) -> dict[str, object]:
    article: dict[str, object] = {
        "title": title,
        "description": "A description",
        "body": "An article body",
    }
    if tags is not None:
        article["tagList"] = tags
    return {"article": article}


def _create_article(
    client: TestClient,
    token: str,
    title: str,
    tags: list[str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/articles",
        headers={"Authorization": f"Token {token}"},
        json=_article_input(title, tags),
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, object], response.json()["article"])


def _update_article(
    client: TestClient,
    token: str,
    slug: str,
    changes: dict[str, object],
) -> dict[str, object]:
    response = client.put(
        f"/api/articles/{slug}",
        headers={"Authorization": f"Token {token}"},
        json={"article": changes},
    )
    assert response.status_code == status.HTTP_200_OK
    return cast(dict[str, object], response.json()["article"])


def _counts(session: Session) -> tuple[int, int, int, int]:
    counts = tuple(
        session.scalar(select(func.count()).select_from(model))
        for model in (User, Article, Tag, ArticleTag)
    )
    assert all(count is not None for count in counts)
    return counts  # type: ignore[return-value]


def test_same_title_articles_have_distinct_retrievable_slugs(
    client: TestClient,
) -> None:
    """제목이 같은 두 게시글도 서로 다른 주소로 각각 조회된다."""
    # Arrange
    _, token = _register_user(client)
    title = f"Shared title {uuid4().hex}"

    # Act
    first = _create_article(client, token, title)
    second = _create_article(client, token, title)
    first_read = client.get(f"/api/articles/{first['slug']}")
    second_read = client.get(f"/api/articles/{second['slug']}")

    # Assert
    assert first["slug"] != second["slug"]
    assert first_read.status_code == status.HTTP_200_OK
    assert second_read.status_code == status.HTTP_200_OK
    assert first_read.json()["article"] == first
    assert second_read.json()["article"] == second


def test_omitted_tag_list_is_empty_on_create_and_read(
    client: TestClient,
) -> None:
    """tagList를 생략하면 생성 응답과 재조회에서 태그 목록이 비어 있다."""
    # Arrange
    _, token = _register_user(client)

    # Act
    created = _create_article(client, token, f"Untagged {uuid4().hex}")
    read = client.get(f"/api/articles/{created['slug']}")

    # Assert
    assert created["tagList"] == []
    assert read.status_code == status.HTTP_200_OK
    assert read.json()["article"]["tagList"] == []


def test_create_article_without_auth_returns_401_without_new_records(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """인증 없이 게시글을 생성하면 401을 반환하고 신규 레코드를 만들지 않는다."""
    # Arrange
    with test_session_factory() as session:
        before = _counts(session)

    # Act
    unauthorized = client.post("/api/articles", json=_article_input("No auth"))

    # Assert
    assert unauthorized.status_code == status.HTTP_401_UNAUTHORIZED
    with test_session_factory() as session:
        assert _counts(session) == before


@pytest.mark.parametrize(
    "invalid_field",
    ["title", "description", "body", "tagList"],
    ids=["blank-title", "blank-description", "blank-body", "null-tag-list"],
)
def test_create_article_with_invalid_field_returns_422_without_new_records(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    invalid_field: str,
) -> None:
    """필수 텍스트가 공백이거나 tagList가 null이면 422를 반환하고 저장하지 않는다."""
    # Arrange
    _, token = _register_user(client)
    with test_session_factory() as session:
        before = _counts(session)
    payload = _article_input(f"Invalid {uuid4().hex}", [f"unused-{uuid4().hex}"])
    article = cast(dict[str, object], payload["article"])
    article[invalid_field] = None if invalid_field == "tagList" else "   "

    # Act
    invalid = client.post(
        "/api/articles",
        headers={"Authorization": f"Token {token}"},
        json=payload,
    )

    # Assert
    assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    if invalid_field == "tagList":
        assert "tagList" in invalid.json()["errors"]
    else:
        assert invalid.json() == {"errors": {invalid_field: ["can't be blank"]}}
    with test_session_factory() as session:
        assert _counts(session) == before


def test_article_commit_failure_leaves_no_new_records_and_allows_retry(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """커밋 실패 후 신규 레코드가 남지 않고 같은 요청을 다시 보내면 성공한다."""
    # Arrange
    _, token = _register_user(server_error_client)
    title = f"Rollback {uuid4().hex}"
    tag = f"rollback-{uuid4().hex}"
    with test_session_factory() as session:
        before = _counts(session)

    def fail_after_flush(session: Session) -> None:
        session.flush()
        raise RuntimeError("simulated commit failure")

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        failed = server_error_client.post(
            "/api/articles",
            headers={"Authorization": f"Token {token}"},
            json=_article_input(title, [tag]),
        )
    with test_session_factory() as session:
        after_failure = _counts(session)
        failed_article = session.scalar(select(Article).where(Article.title == title))
        failed_tag = session.scalar(select(Tag).where(Tag.name == tag))
    recovered = _create_article(server_error_client, token, title, [tag])

    # Assert
    assert failed.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert after_failure == before
    assert failed_article is None
    assert failed_tag is None
    assert recovered["title"] == title


def test_update_article_changes_only_requested_body_and_preserves_tags(
    client: TestClient,
) -> None:
    """본문만 수정하면 다른 내용과 태그·작성 시각을 보존하고 수정 시각을 갱신한다."""
    # Arrange
    _, token = _register_user(client)
    tags = [f"first-{uuid4().hex}", f"second-{uuid4().hex}"]
    created = _create_article(client, token, f"Partial {uuid4().hex}", tags)

    # Act
    updated = _update_article(
        client, token, cast(str, created["slug"]), {"body": "Updated body"}
    )
    reread = client.get(f"/api/articles/{created['slug']}")

    # Assert
    assert updated == {
        **created,
        "body": "Updated body",
        "updatedAt": updated["updatedAt"],
    }
    assert updated["updatedAt"] != created["updatedAt"]
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == updated


def test_title_changes_keep_previous_links_to_the_same_article(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """제목을 여러 번 바꿔도 이전 주소들이 같은 게시글의 최신 내용을 보여준다."""
    # Arrange
    _, token = _register_user(client)
    created = _create_article(client, token, f"Original {uuid4().hex}")
    with test_session_factory() as session:
        original = session.scalar(
            select(Article).where(Article.slug == created["slug"])
        )
        assert original is not None
        original_id = original.id
        public_id = original.public_id
    new_title = f"Changed {uuid4().hex}"
    final_title = f"Final {uuid4().hex}"

    # Act
    first_update = _update_article(
        client, token, cast(str, created["slug"]), {"title": new_title}
    )
    final = _update_article(
        client, token, cast(str, first_update["slug"]), {"title": final_title}
    )
    reads = [
        client.get(f"/api/articles/{slug}")
        for slug in (created["slug"], first_update["slug"], final["slug"])
    ]
    with test_session_factory() as session:
        stored = session.scalar(select(Article).where(Article.slug == final["slug"]))

    # Assert
    assert final["title"] == final_title
    assert len({created["slug"], first_update["slug"], final["slug"]}) == 3
    assert final["createdAt"] == created["createdAt"]
    assert final["updatedAt"] != created["updatedAt"]
    assert all(read.status_code == status.HTTP_200_OK for read in reads)
    assert all(read.json()["article"] == final for read in reads)
    assert stored is not None and stored.id == original_id
    assert stored.public_id == public_id
    assert all(
        cast(str, slug).endswith(public_id.hex)
        for slug in (created["slug"], first_update["slug"], final["slug"])
    )


def test_title_change_to_existing_title_keeps_articles_distinct(
    client: TestClient,
) -> None:
    """다른 게시글과 같은 제목으로 바꿔도 두 게시글의 주소와 내용은 구별된다."""
    # Arrange
    _, token = _register_user(client)
    target_title = f"Target {uuid4().hex}"
    existing = _create_article(client, token, target_title)
    changing = _create_article(client, token, f"Original {uuid4().hex}")

    # Act
    updated = _update_article(
        client, token, cast(str, changing["slug"]), {"title": target_title}
    )
    existing_read = client.get(f"/api/articles/{existing['slug']}")
    previous_read = client.get(f"/api/articles/{changing['slug']}")
    updated_read = client.get(f"/api/articles/{updated['slug']}")

    # Assert
    assert updated["slug"] != existing["slug"]
    assert updated["slug"] != changing["slug"]
    assert existing_read.status_code == status.HTTP_200_OK
    assert existing_read.json()["article"] == existing
    assert previous_read.status_code == status.HTTP_200_OK
    assert previous_read.json()["article"] == updated
    assert updated_read.status_code == status.HTTP_200_OK
    assert updated_read.json()["article"] == updated


def test_replacing_article_tags_preserves_order_and_shared_links(
    client: TestClient,
) -> None:
    """태그를 교체해도 요청 순서와 다른 게시글의 공유 태그 관계가 유지된다."""
    # Arrange
    _, token = _register_user(client)
    shared = f"shared-{uuid4().hex}"
    removed = f"removed-{uuid4().hex}"
    added = f"added-{uuid4().hex}"
    first = _create_article(client, token, f"First {uuid4().hex}", [shared, removed])
    second = _create_article(client, token, f"Second {uuid4().hex}", [shared])

    # Act
    updated = _update_article(
        client, token, cast(str, first["slug"]), {"tagList": [added, shared]}
    )
    first_read = client.get(f"/api/articles/{first['slug']}")
    second_read = client.get(f"/api/articles/{second['slug']}")
    tags = client.get("/api/tags")

    # Assert
    assert updated["tagList"] == [added, shared]
    assert first_read.status_code == status.HTTP_200_OK
    assert first_read.json()["article"]["tagList"] == [added, shared]
    assert second_read.status_code == status.HTTP_200_OK
    assert second_read.json()["article"]["tagList"] == [shared]
    assert tags.status_code == status.HTTP_200_OK
    assert added in tags.json()["tags"]
    assert shared in tags.json()["tags"]
    assert removed not in tags.json()["tags"]


def test_removing_last_tag_link_removes_tag_name(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """마지막 게시글의 태그 연결을 제거하면 미사용 태그 이름도 사라진다."""
    # Arrange
    _, token = _register_user(client)
    tag = f"last-{uuid4().hex}"
    first = _create_article(client, token, f"First {uuid4().hex}", [tag])
    second = _create_article(client, token, f"Second {uuid4().hex}", [tag])

    # Act
    first_updated = _update_article(
        client, token, cast(str, first["slug"]), {"tagList": []}
    )
    while_shared = client.get("/api/tags")
    second_updated = _update_article(
        client, token, cast(str, second["slug"]), {"tagList": []}
    )
    after_last = client.get("/api/tags")
    with test_session_factory() as session:
        stored_tag = session.scalar(select(Tag).where(Tag.name == tag))

    # Assert
    assert first_updated["tagList"] == []
    assert while_shared.status_code == status.HTTP_200_OK
    assert tag in while_shared.json()["tags"]
    assert second_updated["tagList"] == []
    assert after_last.status_code == status.HTTP_200_OK
    assert tag not in after_last.json()["tags"]
    assert stored_tag is None


@pytest.mark.parametrize("first_action", ["remove", "reuse"])
def test_concurrent_last_tag_removal_and_reuse_preserves_new_link(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    first_action: str,
) -> None:
    """마지막 태그 연결 제거와 재사용이 겹쳐도 새 글의 연결이 유지된다."""
    # Arrange
    _, token = _register_user(client)
    tag = f"reused-{uuid4().hex}"
    original = _create_article(client, token, f"Original {uuid4().hex}", [tag])
    newcomer = _create_article(client, token, f"Newcomer {uuid4().hex}")

    def update_tags(slug: str, names: list[str]) -> Response:
        return client.put(
            f"/api/articles/{slug}",
            headers={"Authorization": f"Token {token}"},
            json={"article": {"tagList": names}},
        )

    actions = {
        "remove": (cast(str, original["slug"]), []),
        "reuse": (cast(str, newcomer["slug"]), [tag]),
    }

    # Act
    with test_session_factory() as lock_session:
        locked_tag = lock_session.scalar(
            select(Tag).where(Tag.name == tag).with_for_update()
        )
        assert locked_tag is not None

        def wait_for_blocked_requests(expected: int) -> None:
            deadline = monotonic() + 5
            while monotonic() < deadline:
                with test_session_factory() as monitor:
                    blocked = monitor.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND wait_event_type = 'Lock'"
                        )
                    )
                if blocked is not None and blocked >= expected:
                    return
                sleep(0.01)
            pytest.fail(f"Expected {expected} requests waiting for a DB lock")

        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                first = executor.submit(update_tags, *actions[first_action])
                wait_for_blocked_requests(1)
                second_action = "reuse" if first_action == "remove" else "remove"
                second = executor.submit(update_tags, *actions[second_action])
                wait_for_blocked_requests(2)
            finally:
                lock_session.rollback()
            first_response = first.result(timeout=5)
            second_response = second.result(timeout=5)

    original_read = client.get(f"/api/articles/{original['slug']}")
    newcomer_read = client.get(f"/api/articles/{newcomer['slug']}")
    tags = client.get("/api/tags")
    with test_session_factory() as session:
        stored_tag = session.scalar(select(Tag).where(Tag.name == tag))
        stored_newcomer = session.scalar(
            select(Article).where(Article.slug == newcomer["slug"])
        )
        links = (
            session.scalars(
                select(ArticleTag).where(ArticleTag.tag_id == stored_tag.id)
            ).all()
            if stored_tag is not None
            else []
        )

    # Assert
    assert first_response.status_code == status.HTTP_200_OK
    assert second_response.status_code == status.HTTP_200_OK
    assert original_read.status_code == status.HTTP_200_OK
    assert original_read.json()["article"]["tagList"] == []
    assert newcomer_read.status_code == status.HTTP_200_OK
    assert newcomer_read.json()["article"]["tagList"] == [tag]
    assert tags.status_code == status.HTTP_200_OK
    assert tag in tags.json()["tags"]
    assert stored_tag is not None
    assert stored_newcomer is not None
    assert len(links) == 1 and links[0].article_id == stored_newcomer.id


def test_update_article_without_auth_returns_401_and_preserves_article(
    client: TestClient,
) -> None:
    """인증 없이 수정하면 거부되고 게시글 내용은 유지된다."""
    # Arrange
    _, token = _register_user(client)
    created = _create_article(client, token, f"Protected {uuid4().hex}")

    # Act
    rejected = client.put(
        f"/api/articles/{created['slug']}",
        json={"article": {"body": "Unauthorized change"}},
    )
    reread = client.get(f"/api/articles/{created['slug']}")

    # Assert
    assert rejected.status_code == status.HTTP_401_UNAUTHORIZED
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == created


def test_update_article_by_other_user_returns_403_and_preserves_article(
    client: TestClient,
) -> None:
    """다른 사용자의 수정은 거부되고 원래 게시글과 태그가 유지된다."""
    # Arrange
    _, owner_token = _register_user(client)
    _, other_token = _register_user(client)
    created = _create_article(
        client, owner_token, f"Owned {uuid4().hex}", [f"kept-{uuid4().hex}"]
    )

    # Act
    rejected = client.put(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {other_token}"},
        json={"article": {"title": "Stolen", "tagList": []}},
    )
    reread = client.get(f"/api/articles/{created['slug']}")

    # Assert
    assert rejected.status_code == status.HTTP_403_FORBIDDEN
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == created


@pytest.mark.parametrize(
    "invalid_field",
    ["title", "description", "body", "tagList"],
    ids=["blank-title", "blank-description", "blank-body", "null-tag-list"],
)
def test_invalid_article_update_is_rejected_without_changing_article(
    client: TestClient,
    invalid_field: str,
) -> None:
    """제목·설명·본문이 공백이거나 tagList가 null이면 수정하지 않는다."""
    # Arrange
    _, token = _register_user(client)
    created = _create_article(
        client, token, f"Valid {uuid4().hex}", [f"stable-{uuid4().hex}"]
    )
    changes: dict[str, object] = {
        "body": "Should not save",
        "description": "Should not save",
        invalid_field: None if invalid_field == "tagList" else "   ",
    }

    # Act
    rejected = client.put(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {token}"},
        json={"article": changes},
    )
    reread = client.get(f"/api/articles/{created['slug']}")

    # Assert
    assert rejected.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert invalid_field in rejected.json()["errors"]
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == created


@pytest.mark.parametrize(
    "failure_kind",
    ["python", "postgres"],
    ids=["python-exception-after-flush", "postgres-error-after-flush"],
)
def test_article_update_save_failure_restores_content_and_tags(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    """Python 예외나 PostgreSQL 오류로 저장에 실패해도 글과 태그가 유지된다."""
    # Arrange
    _, token = _register_user(server_error_client)
    old_tag = f"old-{uuid4().hex}"
    new_tag = f"new-{uuid4().hex}"
    created = _create_article(
        server_error_client, token, f"Before {uuid4().hex}", [old_tag]
    )
    postgres_error_seen = False

    def fail_after_flush(session: Session) -> None:
        nonlocal postgres_error_seen
        session.flush()
        if failure_kind == "python":
            raise RuntimeError("simulated commit failure")
        try:
            session.execute(text("SELECT 1 / 0"))
        except DBAPIError:
            postgres_error_seen = True
            raise

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        rejected = server_error_client.put(
            f"/api/articles/{created['slug']}",
            headers={"Authorization": f"Token {token}"},
            json={
                "article": {
                    "title": f"After {uuid4().hex}",
                    "body": "Changed",
                    "tagList": [new_tag],
                }
            },
        )
    reread = server_error_client.get(f"/api/articles/{created['slug']}")
    tags = server_error_client.get("/api/tags")
    with test_session_factory() as session:
        old_stored = session.scalar(select(Tag).where(Tag.name == old_tag))
        new_stored = session.scalar(select(Tag).where(Tag.name == new_tag))

    # Assert
    assert rejected.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    if failure_kind == "postgres":
        assert postgres_error_seen
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == created
    assert tags.status_code == status.HTTP_200_OK
    assert old_tag in tags.json()["tags"]
    assert new_tag not in tags.json()["tags"]
    assert old_stored is not None
    assert new_stored is None


def test_deleting_renamed_article_invalidates_previous_and_current_links(
    client: TestClient,
) -> None:
    """제목 변경 전후의 주소는 게시글을 삭제하면 모두 조회되지 않는다."""
    # Arrange
    _, token = _register_user(client)
    created = _create_article(client, token, f"Original {uuid4().hex}")
    updated = _update_article(
        client, token, cast(str, created["slug"]), {"title": f"Changed {uuid4().hex}"}
    )

    # Act
    deleted = client.delete(
        f"/api/articles/{updated['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    previous_read = client.get(f"/api/articles/{created['slug']}")
    current_read = client.get(f"/api/articles/{updated['slug']}")

    # Assert
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert deleted.content == b""
    assert previous_read.status_code == status.HTTP_404_NOT_FOUND
    assert current_read.status_code == status.HTTP_404_NOT_FOUND


def test_deleting_articles_preserves_shared_tag_until_last_link_is_removed(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """첫 글 삭제로 고유 태그만 사라지고 공유 태그는 두 번째 글 삭제까지 유지된다."""
    # Arrange
    _, token = _register_user(client)
    shared = f"shared-{uuid4().hex}"
    exclusive = f"exclusive-{uuid4().hex}"
    first = _create_article(client, token, f"First {uuid4().hex}", [shared, exclusive])
    second = _create_article(client, token, f"Second {uuid4().hex}", [shared])
    with test_session_factory() as session:
        stored_first = session.scalar(
            select(Article).where(Article.slug == first["slug"])
        )
        assert stored_first is not None
        first_id = stored_first.id

    # Act
    first_deletion = client.delete(
        f"/api/articles/{first['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    first_read = client.get(f"/api/articles/{first['slug']}")
    second_read = client.get(f"/api/articles/{second['slug']}")
    tags_after_first = client.get("/api/tags")
    with test_session_factory() as session:
        removed_article = session.get(Article, first_id)
        removed_links = session.scalars(
            select(ArticleTag).where(ArticleTag.article_id == first_id)
        ).all()
    second_deletion = client.delete(
        f"/api/articles/{second['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    tags_after_second = client.get("/api/tags")

    # Assert
    assert first_deletion.status_code == status.HTTP_204_NO_CONTENT
    assert first_read.status_code == status.HTTP_404_NOT_FOUND
    assert second_read.status_code == status.HTTP_200_OK
    assert second_read.json()["article"] == second
    assert tags_after_first.status_code == status.HTTP_200_OK
    assert exclusive not in tags_after_first.json()["tags"]
    assert shared in tags_after_first.json()["tags"]
    assert removed_article is None
    assert removed_links == []
    assert second_deletion.status_code == status.HTTP_204_NO_CONTENT
    assert tags_after_second.status_code == status.HTTP_200_OK
    assert shared not in tags_after_second.json()["tags"]


def test_delete_article_by_other_user_returns_403_and_preserves_article(
    client: TestClient,
) -> None:
    """다른 사용자의 삭제는 거부되고 게시글과 태그가 유지된다."""
    # Arrange
    _, owner_token = _register_user(client)
    _, other_token = _register_user(client)
    tag = f"protected-{uuid4().hex}"
    article = _create_article(client, owner_token, f"Owned {uuid4().hex}", [tag])

    # Act
    rejected = client.delete(
        f"/api/articles/{article['slug']}",
        headers={"Authorization": f"Token {other_token}"},
    )
    reread = client.get(f"/api/articles/{article['slug']}")
    tags = client.get("/api/tags")

    # Assert
    assert rejected.status_code == status.HTTP_403_FORBIDDEN
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == article
    assert tags.status_code == status.HTTP_200_OK
    assert tag in tags.json()["tags"]


def test_delete_unknown_article_returns_404(client: TestClient) -> None:
    """존재하지 않는 게시글의 삭제는 404를 반환한다."""
    # Arrange
    _, token = _register_user(client)
    missing_slug = f"missing-{uuid4().hex}"

    # Act
    rejected = client.delete(
        f"/api/articles/{missing_slug}",
        headers={"Authorization": f"Token {token}"},
    )

    # Assert
    assert rejected.status_code == status.HTTP_404_NOT_FOUND
    assert rejected.json() == {"errors": {"article": ["not found"]}}


def test_delete_commit_failure_rolls_back_article_and_tag_links(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """삭제 저장에 실패하면 게시글·태그·연결 관계가 모두 유지된다."""
    # Arrange
    _, token = _register_user(server_error_client)
    tag = f"rollback-{uuid4().hex}"
    article = _create_article(
        server_error_client, token, f"Preserved {uuid4().hex}", [tag]
    )

    def fail_after_flush(session: Session) -> None:
        session.flush()
        raise RuntimeError("simulated commit failure")

    # Act
    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_after_flush)
        rejected = server_error_client.delete(
            f"/api/articles/{article['slug']}",
            headers={"Authorization": f"Token {token}"},
        )
    reread = server_error_client.get(f"/api/articles/{article['slug']}")
    tags = server_error_client.get("/api/tags")
    with test_session_factory() as session:
        stored_article = session.scalar(
            select(Article).where(Article.slug == article["slug"])
        )
        stored_tag = session.scalar(select(Tag).where(Tag.name == tag))
        stored_link = (
            session.scalar(
                select(ArticleTag).where(ArticleTag.article_id == stored_article.id)
            )
            if stored_article is not None
            else None
        )

    # Assert
    assert rejected.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == article
    assert tags.status_code == status.HTTP_200_OK
    assert tag in tags.json()["tags"]
    assert stored_article is not None
    assert stored_tag is not None
    assert stored_link is not None and stored_link.tag_id == stored_tag.id
