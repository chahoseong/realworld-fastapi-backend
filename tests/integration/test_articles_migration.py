from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_article_and_tag_migration_preserves_existing_user_and_creates_tables(
    test_database_url: str,
) -> None:
    """기존 사용자 행을 보존하면서 게시글·태그·연결 테이블을 추가한다."""
    # Arrange
    schema_name = f"article_migration_{uuid4().hex}"
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
            command.upgrade(config, "0001")
            user_id = connection.scalar(
                text(
                    "INSERT INTO users (username, email, password_hash) "
                    "VALUES (:username, :email, :password_hash) RETURNING id"
                ),
                {
                    "username": "existing-user",
                    "email": "existing@example.com",
                    "password_hash": "existing-hash",
                },
            )

            # Act
            command.upgrade(config, "head")

            # Assert
            user = connection.execute(
                text(
                    "SELECT id, username, email, password_hash "
                    "FROM users WHERE id = :user_id"
                ),
                {"user_id": user_id},
            ).one()
            assert tuple(user) == (
                user_id,
                "existing-user",
                "existing@example.com",
                "existing-hash",
            )
            assert {"users", "articles", "tags", "article_tags"}.issubset(
                inspect(connection).get_table_names()
            )
    finally:
        schema_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin_engine.dispose()


def test_public_id_migration_backfills_uuid_without_changing_slug(
    test_database_url: str,
) -> None:
    """기존 slug의 UUID를 public_id에 채우고 slug 값은 유지한다."""
    # Arrange
    schema_name = f"article_public_id_migration_{uuid4().hex}"
    public_id = uuid4()
    slug = f"original-title-{public_id.hex}"
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
            command.upgrade(config, "0002")
            user_id = connection.scalar(
                text(
                    "INSERT INTO users (username, email, password_hash) "
                    "VALUES ('existing-user', 'existing@example.com', 'existing-hash') "
                    "RETURNING id"
                )
            )
            article_id = connection.scalar(
                text(
                    "INSERT INTO articles "
                    "(author_id, slug, title, description, body, created_at, updated_at) "
                    "VALUES (:author_id, :slug, 'Original title', 'Description', "
                    "'Body', now(), now()) RETURNING id"
                ),
                {"author_id": user_id, "slug": slug},
            )

            # Act
            command.upgrade(config, "head")
            stored = connection.execute(
                text("SELECT slug, public_id FROM articles WHERE id = :article_id"),
                {"article_id": article_id},
            ).one()

            # Assert
            assert stored.slug == slug
            assert stored.public_id == public_id
            assert {"slug", "public_id"}.issubset(
                {
                    column["name"]
                    for column in inspect(connection).get_columns("articles")
                }
            )
    finally:
        schema_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin_engine.dispose()
