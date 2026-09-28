from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.articles.models import Article, ArticleFavorite
from app.users.models import User


def _existing_data(connection: Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        table: [tuple(row) for row in connection.exec_driver_sql(query)]
        for table, query in {
            "users": "SELECT * FROM users ORDER BY id",
            "articles": "SELECT * FROM articles ORDER BY id",
            "tags": "SELECT * FROM tags ORDER BY id",
            "article_tags": "SELECT * FROM article_tags ORDER BY article_id, position",
            "comments": "SELECT * FROM comments ORDER BY id",
            "user_follows": "SELECT * FROM user_follows ORDER BY follower_id, followed_id",
        }.items()
    }


def test_favorite_migration_preserves_content_and_follows_and_stores_favorites(
    test_database_url: str,
) -> None:
    """0005의 기존 콘텐츠·팔로우 데이터는 0006 적용 후 동일하며, 저장한 즐겨찾기는 새 연결에서도 유지된다."""
    schema_name = f"favorite_migration_{uuid4().hex}"
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
            command.upgrade(config, "0005")
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
            connection.execute(
                text(
                    "INSERT INTO user_follows (follower_id, followed_id) "
                    "VALUES (:viewer_id, :author_id)"
                ),
                {"viewer_id": viewer_id, "author_id": author_id},
            )
            before = _existing_data(connection)

            command.upgrade(config, "0006")

            assert _existing_data(connection) == before
            assert "article_favorites" in inspect(connection).get_table_names()
            connection.execute(
                text(
                    "INSERT INTO article_favorites (user_id, article_id) "
                    "VALUES (:viewer_id, :article_id)"
                ),
                {"viewer_id": viewer_id, "article_id": article_id},
            )
        schema_engine.dispose()
        with schema_engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT user_id, article_id FROM article_favorites")
                ).one()
            ) == (viewer_id, article_id)
            assert _existing_data(connection) == before
    finally:
        schema_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin_engine.dispose()


@pytest.fixture
def stored_favorites(
    test_session_factory: sessionmaker[Session],
) -> tuple[int, int, int, int]:
    with test_session_factory() as session:
        unique_value = uuid4().hex
        first = User(
            username=f"first-{unique_value}",
            email=f"first-{unique_value}@example.com",
            password_hash="not-used",
        )
        second = User(
            username=f"second-{unique_value}",
            email=f"second-{unique_value}@example.com",
            password_hash="not-used",
        )
        session.add_all([first, second])
        session.flush()
        now = datetime.now(UTC)
        articles = [
            Article(
                author_id=user.id,
                slug=f"storage-{uuid4().hex}",
                public_id=uuid4(),
                title="Storage constraints",
                description="Storage constraints",
                body="Keep body",
                created_at=now,
                updated_at=now,
            )
            for user in (first, second)
        ]
        session.add_all(articles)
        session.flush()
        session.add_all(
            [
                ArticleFavorite(user_id=first.id, article_id=articles[0].id),
                ArticleFavorite(user_id=second.id, article_id=articles[1].id),
            ]
        )
        session.commit()
        return first.id, second.id, articles[0].id, articles[1].id


@pytest.mark.parametrize(
    ("violation", "sqlstate"),
    [("duplicate", "23505"), ("missing_user", "23503"), ("missing_article", "23503")],
)
def test_favorite_storage_rejects_duplicates_and_missing_references(
    test_session_factory: sessionmaker[Session],
    stored_favorites: tuple[int, int, int, int],
    violation: str,
    sqlstate: str,
) -> None:
    """DB 자체가 중복 즐겨찾기와 없는 사용자·게시글 참조를 거부하고 기존 유효 관계는 유지한다."""
    first_id, second_id, first_article_id, second_article_id = stored_favorites
    pairs = {
        "duplicate": (first_id, first_article_id),
        "missing_user": (0, first_article_id),
        "missing_article": (first_id, 0),
    }
    user_id, article_id = pairs[violation]
    with test_session_factory() as session:
        with pytest.raises(IntegrityError) as raised:
            with session.begin_nested():
                session.execute(
                    text(
                        "INSERT INTO article_favorites (user_id, article_id) "
                        "VALUES (:user_id, :article_id)"
                    ),
                    {"user_id": user_id, "article_id": article_id},
                )
        assert getattr(raised.value.orig, "sqlstate", None) == sqlstate
    with test_session_factory() as session:
        assert session.get(ArticleFavorite, (first_id, first_article_id)) is not None
        assert session.get(ArticleFavorite, (second_id, second_article_id)) is not None
        if violation != "duplicate":
            assert session.get(ArticleFavorite, (user_id, article_id)) is None


def test_favorite_storage_cascades_article_deletion_and_preserves_other_references(
    test_session_factory: sessionmaker[Session],
    stored_favorites: tuple[int, int, int, int],
) -> None:
    """DB에서 게시글을 삭제하면 그 글의 즐겨찾기만 제거하고, 다른 게시글의 즐겨찾기와 사용자는 유지한다."""
    first_id, second_id, first_article_id, second_article_id = stored_favorites
    with test_session_factory() as session:
        session.execute(delete(Article).where(Article.id == first_article_id))
        session.commit()
    with test_session_factory() as session:
        assert session.get(ArticleFavorite, (first_id, first_article_id)) is None
        assert session.get(ArticleFavorite, (second_id, second_article_id)) is not None
        assert session.get(Article, first_article_id) is None
        assert session.get(Article, second_article_id) is not None
        assert set(
            session.scalars(select(User.id).where(User.id.in_([first_id, second_id])))
        ) == {first_id, second_id}
