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

from app.articles.models import Article, ArticleFavorite, ArticleTag, Tag
from app.comments.models import Comment
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


def _favorite_article(
    client: TestClient, token: str, article: dict[str, object]
) -> dict[str, object]:
    response = client.post(
        f"/api/articles/{article['slug']}/favorite",
        headers={"Authorization": f"Token {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    return cast(dict[str, object], response.json()["article"])


def _favorite_relationships(
    session: Session, article_ids: set[int]
) -> set[tuple[int, int]]:
    return {
        (favorite.user_id, favorite.article_id)
        for favorite in session.scalars(
            select(ArticleFavorite).where(ArticleFavorite.article_id.in_(article_ids))
        )
    }


def _create_comment(
    client: TestClient, token: str, article: dict[str, object], body: str
) -> dict[str, object]:
    response = client.post(
        f"/api/articles/{article['slug']}/comments",
        headers={"Authorization": f"Token {token}"},
        json={"comment": {"body": body}},
    )
    assert response.status_code == status.HTTP_201_CREATED
    return cast(dict[str, object], response.json()["comment"])


@pytest.fixture
def followed_article(
    client: TestClient,
) -> tuple[str, str, dict[str, object]]:
    _, viewer_token = _register_user(client)
    author_name, author_token = _register_user(client)
    article = _create_article(
        client,
        author_token,
        "Followed user's article",
        [f"following-{uuid4().hex}"],
    )
    followed = client.post(
        f"/api/profiles/{author_name}/follow",
        headers={"Authorization": f"Token {viewer_token}"},
    )
    assert followed.status_code == status.HTTP_200_OK
    assert followed.json()["profile"]["following"] is True
    return author_name, viewer_token, article


def test_article_following_depends_on_whether_the_viewer_follows_its_author(
    client: TestClient,
    followed_article: tuple[str, str, dict[str, object]],
) -> None:
    """게시글 작성자를 팔로우한 조회자에게는 following=true, 다른 조회자와 익명에게는 false를 반환한다."""
    _, viewer_token, article = followed_article
    _, unrelated_token = _register_user(client)

    for headers, expected_following in (
        ({"Authorization": f"Token {viewer_token}"}, True),
        ({"Authorization": f"Token {unrelated_token}"}, False),
        ({}, False),
    ):
        response = client.get(f"/api/articles/{article['slug']}", headers=headers)
        expected_article = article | {
            "author": cast(dict[str, object], article["author"])
            | {"following": expected_following}
        }
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"article": expected_article}


def test_unfollowing_article_author_changes_following_without_changing_article(
    client: TestClient,
    followed_article: tuple[str, str, dict[str, object]],
) -> None:
    """게시글 작성자의 팔로우를 해제하면 새 조회에서 following=false가 되고, 게시글 내용과 식별자는 유지된다."""
    author_name, viewer_token, article = followed_article
    headers = {"Authorization": f"Token {viewer_token}"}
    before = client.get(f"/api/articles/{article['slug']}", headers=headers)
    assert before.status_code == status.HTTP_200_OK
    assert before.json()["article"]["author"]["following"] is True

    unfollowed = client.delete(f"/api/profiles/{author_name}/follow", headers=headers)
    assert unfollowed.status_code == status.HTTP_200_OK
    assert unfollowed.json()["profile"]["following"] is False
    reread = client.get(f"/api/articles/{article['slug']}", headers=headers)
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json() == {"article": article}


def test_article_favorite_state_is_viewer_specific_and_count_includes_all_users(
    client: TestClient,
) -> None:
    """게시글을 조회하면, 조회한 사용자가 해당 게시글을 즐겨찾기했는지 응답에 표시되며, 해당 게시글을 즐겨찾기한 사용자의 수가 표시된다."""
    author_name, author_token = _register_user(client)
    _, first_token = _register_user(client)
    _, second_token = _register_user(client)
    article = _create_article(
        client, author_token, "Viewer favorites", [f"fav-{uuid4().hex}"]
    )
    followed = client.post(
        f"/api/profiles/{author_name}/follow",
        headers={"Authorization": f"Token {first_token}"},
    )
    assert followed.status_code == status.HTTP_200_OK

    for method, token, first_favorited, second_favorited, expected_count in (
        ("POST", first_token, True, False, 1),
        ("POST", second_token, True, True, 2),
        ("DELETE", first_token, False, True, 1),
        ("DELETE", second_token, False, False, 0),
    ):
        changed = client.request(
            method,
            f"/api/articles/{article['slug']}/favorite",
            headers={"Authorization": f"Token {token}"},
        )
        assert changed.status_code == status.HTTP_200_OK
        for viewer_token, expected_favorited, expected_following in (
            (first_token, first_favorited, True),
            (second_token, second_favorited, False),
            (None, False, False),
        ):
            expected_article = article | {
                "favorited": expected_favorited,
                "favoritesCount": expected_count,
                "author": cast(dict[str, object], article["author"])
                | {"following": expected_following},
            }
            reread = client.get(
                f"/api/articles/{article['slug']}",
                headers=(
                    {"Authorization": f"Token {viewer_token}"}
                    if viewer_token is not None
                    else {}
                ),
            )
            assert reread.status_code == status.HTTP_200_OK
            assert reread.json() == {"article": expected_article}
            if viewer_token == token:
                assert changed.json() == {"article": expected_article}


def test_article_creation_and_update_expose_the_authors_public_fields(
    client: TestClient,
) -> None:
    """팔로워와 팔로우 대상이 있는 작성자도 작성·수정 응답에는 자기 공개 정보와 following=false만 담긴다."""
    author_name, token = _register_user(client)
    other_name, other_token = _register_user(client)
    headers = {"Authorization": f"Token {token}"}
    updated_profile = client.put(
        "/api/user",
        headers=headers,
        json={
            "user": {"bio": "Article author", "image": "https://example.com/avatar.png"}
        },
    )
    assert updated_profile.status_code == status.HTTP_200_OK
    for target, follower_token in (
        (other_name, token),
        (author_name, other_token),
    ):
        followed = client.post(
            f"/api/profiles/{target}/follow",
            headers={"Authorization": f"Token {follower_token}"},
        )
        assert followed.status_code == status.HTTP_200_OK

    created = _create_article(client, token, "Author public fields")
    updated = _update_article(
        client, token, str(created["slug"]), {"body": "Updated body"}
    )
    expected_author = {
        "username": author_name,
        "bio": "Article author",
        "image": "https://example.com/avatar.png",
        "following": False,
    }
    assert created["author"] == expected_author
    assert updated["author"] == expected_author


@pytest.mark.parametrize("authorization", ["", "Token invalid"])
@pytest.mark.parametrize("article_exists", [True, False], ids=["existing", "missing"])
def test_article_read_rejects_invalid_auth_before_article_lookup(
    client: TestClient, authorization: str, article_exists: bool
) -> None:
    """인증 헤더가 비어 있거나 토큰이 잘못되면 게시글 존재 여부와 관계없이 조회를 401로 거부한다."""
    _, token = _register_user(client)
    slug = (
        str(_create_article(client, token, "Optional authentication")["slug"])
        if article_exists
        else f"unknown-{uuid4().hex}"
    )
    response = client.get(
        f"/api/articles/{slug}", headers={"Authorization": authorization}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"errors": {"token": ["is invalid"]}}


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


def test_failed_article_creation_leaves_no_new_records_and_allows_retry(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """게시글 저장에 실패하면 새 글·태그가 남지 않고 같은 요청을 재시도할 수 있다."""
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


@pytest.mark.parametrize("owner_favorited", [False, True])
def test_update_article_changes_only_requested_body_and_preserves_tags(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    owner_favorited: bool,
) -> None:
    """본문만 수정하면 다른 내용과 태그·작성 시각을 보존하고 수정 시각을 갱신한다."""
    # Arrange
    _, token = _register_user(client)
    tags = [f"first-{uuid4().hex}", f"second-{uuid4().hex}"]
    created = _create_article(client, token, f"Partial {uuid4().hex}", tags)
    _, other_token = _register_user(client)
    _favorite_article(client, other_token, created)
    if owner_favorited:
        _favorite_article(client, token, created)
    expected = created | {
        "favorited": owner_favorited,
        "favoritesCount": 2 if owner_favorited else 1,
    }
    with test_session_factory() as session:
        stored = session.scalar(select(Article).where(Article.slug == created["slug"]))
        assert stored is not None
        article_id = stored.id
        before_relationships = _favorite_relationships(session, {article_id})

    # Act
    updated = _update_article(
        client, token, cast(str, created["slug"]), {"body": "Updated body"}
    )
    reread = client.get(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    with test_session_factory() as session:
        assert _favorite_relationships(session, {article_id}) == before_relationships

    # Assert
    assert updated == {
        **expected,
        "body": "Updated body",
        "updatedAt": updated["updatedAt"],
    }
    assert updated["updatedAt"] != created["updatedAt"]
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == updated


@pytest.mark.parametrize("owner_favorited", [False, True])
def test_title_changes_preserve_public_id_and_previous_links(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    owner_favorited: bool,
) -> None:
    """제목을 여러 번 바꿔도 public id와 이전 주소의 최신 조회 결과가 유지된다."""
    # Arrange
    _, token = _register_user(client)
    created = _create_article(client, token, f"Original {uuid4().hex}")
    public_suffix = cast(str, created["slug"]).rsplit("-", 1)[-1]
    new_title = f"Changed {uuid4().hex}"
    final_title = f"Final {uuid4().hex}"
    _, other_token = _register_user(client)
    _favorite_article(client, other_token, created)
    if owner_favorited:
        _favorite_article(client, token, created)
    expected_count = 2 if owner_favorited else 1
    with test_session_factory() as session:
        stored = session.scalar(select(Article).where(Article.slug == created["slug"]))
        assert stored is not None
        article_id = stored.id
        before_relationships = _favorite_relationships(session, {article_id})

    # Act
    first_update = _update_article(
        client, token, cast(str, created["slug"]), {"title": new_title}
    )
    final = _update_article(
        client, token, cast(str, first_update["slug"]), {"title": final_title}
    )
    reads = [
        client.get(f"/api/articles/{slug}", headers={"Authorization": f"Token {token}"})
        for slug in (created["slug"], first_update["slug"], final["slug"])
    ]

    # Assert
    assert final["title"] == final_title
    assert len({created["slug"], first_update["slug"], final["slug"]}) == 3
    assert final["createdAt"] == created["createdAt"]
    assert final["updatedAt"] != created["updatedAt"]
    assert all(read.status_code == status.HTTP_200_OK for read in reads)
    assert all(read.json()["article"] == final for read in reads)
    assert first_update["favorited"] is owner_favorited
    assert final["favorited"] is owner_favorited
    assert first_update["favoritesCount"] == final["favoritesCount"] == expected_count
    assert len(public_suffix) == 32
    assert all(
        cast(str, slug).rsplit("-", 1)[-1] == public_suffix
        for slug in (created["slug"], first_update["slug"], final["slug"])
    )
    with test_session_factory() as session:
        stored = session.get(Article, article_id)
        assert stored is not None and stored.slug == final["slug"]
        assert _favorite_relationships(session, {article_id}) == before_relationships


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
        lock_pid = lock_session.scalar(text("SELECT pg_backend_pid()"))
        assert lock_pid is not None

        def wait_for_blocked_requests(expected: int) -> None:
            deadline = monotonic() + 5
            while monotonic() < deadline:
                with test_session_factory() as monitor:
                    blocked = monitor.scalar(
                        text(
                            "WITH RECURSIVE blocked(pid) AS ("
                            "SELECT pid FROM pg_stat_activity "
                            "WHERE :lock_pid = ANY(pg_blocking_pids(pid)) "
                            "UNION "
                            "SELECT activity.pid FROM pg_stat_activity AS activity "
                            "JOIN blocked AS prior "
                            "ON prior.pid = ANY(pg_blocking_pids(activity.pid))"
                            ") SELECT count(*) FROM blocked"
                        ),
                        {"lock_pid": lock_pid},
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
    created = _favorite_article(client, token, created)

    # Act
    rejected = client.put(
        f"/api/articles/{created['slug']}",
        json={"article": {"body": "Unauthorized change"}},
    )
    reread = client.get(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {token}"},
    )

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
    created = _favorite_article(client, owner_token, created)

    # Act
    rejected = client.put(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {other_token}"},
        json={"article": {"title": "Stolen", "tagList": []}},
    )
    reread = client.get(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {owner_token}"},
    )

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
    created = _favorite_article(client, token, created)
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
    reread = client.get(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {token}"},
    )

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
    """Python 예외나 PostgreSQL 오류로 수정 저장에 실패해도 글과 태그가 유지되며, 오류 제거 후 다시 수정할 수 있다."""
    # Arrange
    _, token = _register_user(server_error_client)
    old_tag = f"old-{uuid4().hex}"
    new_tag = f"new-{uuid4().hex}"
    created = _create_article(
        server_error_client, token, f"Before {uuid4().hex}", [old_tag]
    )
    _, other_token = _register_user(server_error_client)
    _favorite_article(server_error_client, other_token, created)
    created = _favorite_article(server_error_client, token, created)
    with test_session_factory() as session:
        stored = session.scalar(select(Article).where(Article.slug == created["slug"]))
        assert stored is not None
        article_id = stored.id
        before_relationships = _favorite_relationships(session, {article_id})
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
    reread = server_error_client.get(
        f"/api/articles/{created['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    tags = server_error_client.get("/api/tags")
    with test_session_factory() as session:
        old_stored = session.scalar(select(Tag).where(Tag.name == old_tag))
        new_stored = session.scalar(select(Tag).where(Tag.name == new_tag))
        assert _favorite_relationships(session, {article_id}) == before_relationships

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

    recovered = _update_article(
        server_error_client, token, cast(str, created["slug"]), {"body": "Retry saved"}
    )
    assert recovered == created | {
        "body": "Retry saved",
        "updatedAt": recovered["updatedAt"],
    }


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


def test_article_deletion_removes_own_relations_and_preserves_other_data(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """게시글 삭제로 고유 태그는 사라지고, 공유 태그는 마지막 연결이 삭제될 때까지 유지된다.

    삭제한 글의 댓글·즐겨찾기도 함께 제거하며, 다른 게시글의 데이터와 사용자는 유지한다.
    """
    # Arrange
    owner_name, token = _register_user(client)
    other_name, other_token = _register_user(client)
    shared = f"shared-{uuid4().hex}"
    exclusive = f"exclusive-{uuid4().hex}"
    first = _create_article(client, token, f"First {uuid4().hex}", [shared, exclusive])
    second = _create_article(client, token, f"Second {uuid4().hex}", [shared])
    _favorite_article(client, token, first)
    _favorite_article(client, other_token, first)
    second = _favorite_article(client, other_token, second) | {"favorited": False}
    removed_comment = _create_comment(client, other_token, first, "On removed article")
    kept_comment = _create_comment(client, other_token, second, "On kept article")
    with test_session_factory() as session:
        stored_first = session.scalar(
            select(Article).where(Article.slug == first["slug"])
        )
        assert stored_first is not None
        first_id = stored_first.id
        stored_second = session.scalar(
            select(Article).where(Article.slug == second["slug"])
        )
        assert stored_second is not None
        second_id = stored_second.id
        kept_relationships = _favorite_relationships(session, {second_id})

    # Act
    first_deletion = client.delete(
        f"/api/articles/{first['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    first_read = client.get(f"/api/articles/{first['slug']}")
    second_read = client.get(f"/api/articles/{second['slug']}")
    tags_after_first = client.get("/api/tags")
    second_comments = client.get(f"/api/articles/{second['slug']}/comments")
    with test_session_factory() as session:
        removed_article = session.get(Article, first_id)
        removed_links = session.scalars(
            select(ArticleTag).where(ArticleTag.article_id == first_id)
        ).all()
        assert (
            _favorite_relationships(session, {first_id, second_id})
            == kept_relationships
        )
        assert session.get(Comment, removed_comment["id"]) is None
        assert session.get(Comment, kept_comment["id"]) is not None
        assert (
            session.scalar(select(User).where(User.username == owner_name)) is not None
        )
        assert (
            session.scalar(select(User).where(User.username == other_name)) is not None
        )
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
    assert second_comments.status_code == status.HTTP_200_OK
    assert second_comments.json() == {"comments": [kept_comment]}
    assert tags_after_first.status_code == status.HTTP_200_OK
    assert exclusive not in tags_after_first.json()["tags"]
    assert shared in tags_after_first.json()["tags"]
    assert removed_article is None
    assert removed_links == []
    assert second_deletion.status_code == status.HTTP_204_NO_CONTENT
    assert tags_after_second.status_code == status.HTTP_200_OK
    assert shared not in tags_after_second.json()["tags"]
    with test_session_factory() as session:
        assert _favorite_relationships(session, {first_id, second_id}) == set()
        assert session.get(Comment, kept_comment["id"]) is None


@pytest.mark.parametrize(
    "authenticated", [False, True], ids=["missing-auth", "other-user"]
)
def test_rejected_article_deletion_preserves_content_and_favorites(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    authenticated: bool,
) -> None:
    """인증이 없거나 작성자가 아닌 사용자의 삭제는 거부되고 기존 게시글과 관련 데이터가 유지된다."""
    # Arrange
    _, owner_token = _register_user(client)
    _, other_token = _register_user(client)
    tag = f"protected-{uuid4().hex}"
    article = _create_article(client, owner_token, f"Owned {uuid4().hex}", [tag])
    _favorite_article(client, other_token, article)
    article = _favorite_article(client, owner_token, article)
    comment = _create_comment(client, other_token, article, "Protected comment")
    with test_session_factory() as session:
        stored = session.scalar(select(Article).where(Article.slug == article["slug"]))
        assert stored is not None
        article_id = stored.id
        before_relationships = _favorite_relationships(session, {article_id})

    # Act
    rejected = client.delete(
        f"/api/articles/{article['slug']}",
        headers={"Authorization": f"Token {other_token}"} if authenticated else {},
    )
    reread = client.get(
        f"/api/articles/{article['slug']}",
        headers={"Authorization": f"Token {owner_token}"},
    )
    comments = client.get(f"/api/articles/{article['slug']}/comments")
    tags = client.get("/api/tags")

    # Assert
    assert rejected.status_code == (
        status.HTTP_403_FORBIDDEN if authenticated else status.HTTP_401_UNAUTHORIZED
    )
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == article
    assert tags.status_code == status.HTTP_200_OK
    assert tag in tags.json()["tags"]
    assert comments.status_code == status.HTTP_200_OK
    assert comments.json() == {"comments": [comment]}
    with test_session_factory() as session:
        assert _favorite_relationships(session, {article_id}) == before_relationships


@pytest.mark.parametrize(
    "failure_kind",
    ["python", "postgres"],
    ids=["python-exception-after-flush", "postgres-error-after-flush"],
)
def test_failed_article_deletion_restores_content_and_relations_and_allows_retry(
    server_error_client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    """게시글 삭제 저장에 실패하면 삭제 전 게시글과 관련 데이터가 복구되고, 오류 제거 후 다시 삭제할 수 있다."""
    # Arrange
    _, token = _register_user(server_error_client)
    tag = f"rollback-{uuid4().hex}"
    article = _create_article(
        server_error_client, token, f"Preserved {uuid4().hex}", [tag]
    )
    _, other_token = _register_user(server_error_client)
    _favorite_article(server_error_client, other_token, article)
    article = _favorite_article(server_error_client, token, article)
    comment = _create_comment(server_error_client, other_token, article, "Keep me")
    kept_article = _create_article(
        server_error_client, other_token, f"Kept {uuid4().hex}"
    )
    kept_article = _favorite_article(server_error_client, token, kept_article) | {
        "favorited": False
    }
    with test_session_factory() as session:
        stored = session.scalar(select(Article).where(Article.slug == article["slug"]))
        kept_stored = session.scalar(
            select(Article).where(Article.slug == kept_article["slug"])
        )
        assert stored is not None and kept_stored is not None
        article_id, kept_id = stored.id, kept_stored.id
        before_relationships = _favorite_relationships(session, {article_id, kept_id})
        kept_relationships = _favorite_relationships(session, {kept_id})
    deletion_flushed = False
    postgres_error_seen = False

    def fail_after_flush(session: Session) -> None:
        nonlocal deletion_flushed, postgres_error_seen
        session.flush()
        assert (
            session.scalar(select(Article.id).where(Article.id == article_id)) is None
        )
        assert session.get(Comment, comment["id"]) is None
        assert _favorite_relationships(session, {article_id}) == set()
        deletion_flushed = True
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
        rejected = server_error_client.delete(
            f"/api/articles/{article['slug']}",
            headers={"Authorization": f"Token {token}"},
        )
    reread = server_error_client.get(
        f"/api/articles/{article['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    comments = server_error_client.get(f"/api/articles/{article['slug']}/comments")
    kept_read = server_error_client.get(f"/api/articles/{kept_article['slug']}")
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
        assert (
            _favorite_relationships(session, {article_id, kept_id})
            == before_relationships
        )
        assert session.get(Comment, comment["id"]) is not None

    # Assert
    assert rejected.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert deletion_flushed
    if failure_kind == "postgres":
        assert postgres_error_seen
    assert reread.status_code == status.HTTP_200_OK
    assert reread.json()["article"] == article
    assert tags.status_code == status.HTTP_200_OK
    assert tag in tags.json()["tags"]
    assert stored_article is not None
    assert stored_tag is not None
    assert stored_link is not None and stored_link.tag_id == stored_tag.id
    assert comments.status_code == status.HTTP_200_OK
    assert comments.json() == {"comments": [comment]}
    assert kept_read.status_code == status.HTTP_200_OK
    assert kept_read.json() == {"article": kept_article}

    recovered = server_error_client.delete(
        f"/api/articles/{article['slug']}",
        headers={"Authorization": f"Token {token}"},
    )
    assert recovered.status_code == status.HTTP_204_NO_CONTENT
    assert (
        server_error_client.get(f"/api/articles/{article['slug']}").status_code
        == status.HTTP_404_NOT_FOUND
    )
    with test_session_factory() as session:
        assert session.get(Article, article_id) is None
        assert session.get(Comment, comment["id"]) is None
        assert (
            _favorite_relationships(session, {article_id, kept_id})
            == kept_relationships
        )
