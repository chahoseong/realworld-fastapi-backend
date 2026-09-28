"""Create user favorites linked to articles.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "article_id"),
    )
    op.create_index(
        "ix_article_favorites_article_id", "article_favorites", ["article_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_article_favorites_article_id", table_name="article_favorites")
    op.drop_table("article_favorites")
