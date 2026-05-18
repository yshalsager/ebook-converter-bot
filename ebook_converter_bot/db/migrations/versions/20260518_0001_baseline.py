"""baseline"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260518_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics",
        sa.Column("id", sa.INT(), autoincrement=True, nullable=False),
        sa.Column("format", sa.VARCHAR(), nullable=False),
        sa.Column("input_times", sa.INT(), nullable=False),
        sa.Column("output_times", sa.INT(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chats",
        sa.Column("id", sa.INT(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BIGINT(), nullable=False),
        sa.Column("user_name", sa.VARCHAR(), nullable=False),
        sa.Column("type", sa.INT(), nullable=False),
        sa.Column("usage_times", sa.INT(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "user_option_defaults",
        sa.Column("id", sa.INT(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BIGINT(), nullable=False),
        sa.Column("options_json", sa.TEXT(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_option_defaults_user_id"),
        "user_option_defaults",
        ["user_id"],
        unique=True,
    )
    op.create_table(
        "preferences",
        sa.Column("id", sa.INT(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BIGINT(), nullable=False),
        sa.Column("language", sa.VARCHAR(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["chats.user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("preferences")
    op.drop_index(op.f("ix_user_option_defaults_user_id"), table_name="user_option_defaults")
    op.drop_table("user_option_defaults")
    op.drop_table("chats")
    op.drop_table("analytics")
