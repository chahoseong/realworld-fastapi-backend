from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_comment_migration_preserves_existing_user_article_and_tag(
    test_database_url: str,
) -> None:
    """댓글 저장 구조를 추가해도 기존 사용자·게시글·태그 관계가 유지된다."""
    # Arrange
    schema_name = f"comment_migration_{uuid4().hex}"
    public_id = uuid4()
    slug = f"existing-article-{public_id.hex}"
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
            command.upgrade(config, "0003")
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
                    "(author_id, slug, public_id, title, description, body, "
                    "created_at, updated_at) "
                    "VALUES (:author_id, :slug, CAST(:public_id AS uuid), "
                    "'Existing title', 'Existing description', 'Existing body', "
                    "now(), now()) RETURNING id"
                ),
                {"author_id": user_id, "slug": slug, "public_id": str(public_id)},
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
            before = connection.execute(
                text(
                    "SELECT u.username, u.email, u.password_hash, a.slug, "
                    "a.public_id, a.title, t.name "
                    "FROM users AS u JOIN articles AS a ON a.author_id = u.id "
                    "JOIN article_tags AS link ON link.article_id = a.id "
                    "JOIN tags AS t ON t.id = link.tag_id "
                    "WHERE a.id = :article_id"
                ),
                {"article_id": article_id},
            ).one()

            # Act
            command.upgrade(config, "head")
            after = connection.execute(
                text(
                    "SELECT u.username, u.email, u.password_hash, a.slug, "
                    "a.public_id, a.title, t.name "
                    "FROM users AS u JOIN articles AS a ON a.author_id = u.id "
                    "JOIN article_tags AS link ON link.article_id = a.id "
                    "JOIN tags AS t ON t.id = link.tag_id "
                    "WHERE a.id = :article_id"
                ),
                {"article_id": article_id},
            ).one()

            # Assert
            assert tuple(after) == tuple(before)
            assert "comments" in inspect(connection).get_table_names()
    finally:
        schema_engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        admin_engine.dispose()
