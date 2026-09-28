from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.users.models import User, UserFollow


def _content_snapshot(connection: Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        table: [tuple(row) for row in connection.exec_driver_sql(query)]
        for table, query in {
            "users": "SELECT * FROM users ORDER BY id",
            "articles": "SELECT * FROM articles ORDER BY id",
            "tags": "SELECT * FROM tags ORDER BY id",
            "article_tags": "SELECT * FROM article_tags ORDER BY article_id, position",
            "comments": "SELECT * FROM comments ORDER BY id",
        }.items()
    }


def test_follow_migration_preserves_existing_content_and_stores_relationships(
    test_database_url: str,
) -> None:
    """0004의 모든 기존 데이터는 0005 적용 후 동일하며 관계는 새 연결에서도 유지된다."""
    schema_name = f"follow_migration_{uuid4().hex}"
    admin_engine = create_engine(test_database_url)
    schema_engine = create_engine(
        test_database_url,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
        with schema_engine.begin() as connection:
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "0004")
            author_id = connection.scalar(
                text(
                    "INSERT INTO users (username, email, password_hash, bio, image) "
                    "VALUES ('author', 'author@example.com', 'hash', 'Bio', 'Image') "
                    "RETURNING id"
                )
            )
            viewer_id = connection.scalar(
                text(
                    "INSERT INTO users (username, email, password_hash) "
                    "VALUES ('viewer', 'viewer@example.com', 'hash') RETURNING id"
                )
            )
            article_id = connection.scalar(
                text(
                    "INSERT INTO articles (author_id, slug, public_id, title, "
                    "description, body, created_at, updated_at) VALUES "
                    "(:author_id, 'existing', CAST(:public_id AS uuid), 'Title', "
                    "'Description', 'Body', now(), now()) RETURNING id"
                ),
                {"author_id": author_id, "public_id": str(uuid4())},
            )
            tag_id = connection.scalar(
                text("INSERT INTO tags (name) VALUES ('existing-tag') RETURNING id")
            )
            connection.execute(
                text(
                    "INSERT INTO article_tags (article_id, position, tag_id) "
                    "VALUES (:article_id, 0, :tag_id)"
                ),
                {"article_id": article_id, "tag_id": tag_id},
            )
            connection.execute(
                text(
                    "INSERT INTO comments (article_id, author_id, body, created_at, "
                    "updated_at) VALUES (:article_id, :author_id, 'Comment', now(), now())"
                ),
                {"article_id": article_id, "author_id": author_id},
            )
            before = _content_snapshot(connection)

            command.upgrade(config, "0005")

            assert _content_snapshot(connection) == before
            assert "user_follows" in inspect(connection).get_table_names()
            connection.execute(
                text(
                    "INSERT INTO user_follows (follower_id, followed_id) "
                    "VALUES (:viewer_id, :author_id)"
                ),
                {"viewer_id": viewer_id, "author_id": author_id},
            )
        schema_engine.dispose()
        with schema_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT follower_id, followed_id FROM user_follows")
                ).one()
            ) == (viewer_id, author_id)
            assert _content_snapshot(connection) == before
    finally:
        schema_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin_engine.dispose()


@pytest.mark.parametrize(
    ("violation", "sqlstate"),
    [
        ("duplicate", "23505"),
        ("missing_follower", "23503"),
        ("missing_followed", "23503"),
        ("self", "23514"),
    ],
)
def test_follow_storage_rejects_invalid_relationships(
    test_session_factory: sessionmaker[Session], violation: str, sqlstate: str
) -> None:
    """DB 자체가 중복·없는 사용자 참조·자기 자신 관계를 거부하고 유효 관계를 유지한다."""
    unique_value = uuid4().hex
    with test_session_factory() as session:
        viewer = User(
            username=f"viewer-{unique_value}",
            email=f"viewer-{unique_value}@example.com",
            password_hash="not-used",
        )
        author = User(
            username=f"author-{unique_value}",
            email=f"author-{unique_value}@example.com",
            password_hash="not-used",
        )
        session.add_all([viewer, author])
        session.flush()
        viewer_id, author_id = viewer.id, author.id
        session.add(UserFollow(follower_id=viewer_id, followed_id=author_id))
        session.commit()
        pairs = {
            "duplicate": (viewer_id, author_id),
            "missing_follower": (0, author_id),
            "missing_followed": (viewer_id, 0),
            "self": (viewer_id, viewer_id),
        }
        follower_id, followed_id = pairs[violation]
        with pytest.raises(IntegrityError) as raised:
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO user_follows (follower_id, followed_id) "
                        "VALUES (:follower_id, :followed_id)"
                    ),
                    {"follower_id": follower_id, "followed_id": followed_id},
                )
        assert getattr(raised.value.orig, "sqlstate", None) == sqlstate
    with test_session_factory() as session:
        assert session.get(UserFollow, (viewer_id, author_id)) is not None
        if violation != "duplicate":
            assert session.get(UserFollow, (follower_id, followed_id)) is None
