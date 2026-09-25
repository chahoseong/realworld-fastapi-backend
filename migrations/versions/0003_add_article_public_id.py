"""Keep an article's public UUID when its title changes.

Revision ID: 0003
Revises: 0002
"""

import re
from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLUG_SUFFIX = re.compile(r"-([0-9a-f]{32})$")


def upgrade() -> None:
    op.add_column("articles", sa.Column("public_id", sa.Uuid(), nullable=True))
    connection = op.get_bind()
    articles = connection.execute(sa.text("SELECT id, slug FROM articles")).all()
    for article_id, slug in articles:
        match = _SLUG_SUFFIX.search(slug)
        if match is None:
            raise ValueError(f"Article {article_id} has no UUID suffix in its slug")
        connection.execute(
            sa.text(
                "UPDATE articles SET public_id = :public_id WHERE id = :article_id"
            ),
            {"public_id": UUID(hex=match.group(1)), "article_id": article_id},
        )

    op.alter_column("articles", "public_id", nullable=False)
    op.create_unique_constraint("uq_articles_public_id", "articles", ["public_id"])


def downgrade() -> None:
    op.drop_constraint("uq_articles_public_id", "articles", type_="unique")
    op.drop_column("articles", "public_id")
