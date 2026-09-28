"""Create directed user follow relationships.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_follows",
        sa.Column("follower_id", sa.Integer(), nullable=False),
        sa.Column("followed_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["followed_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("follower_id", "followed_id"),
        sa.CheckConstraint(
            "follower_id <> followed_id", name="ck_user_follows_not_self"
        ),
    )


def downgrade() -> None:
    op.drop_table("user_follows")
