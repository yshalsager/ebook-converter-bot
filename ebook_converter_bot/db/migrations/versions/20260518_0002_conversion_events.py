"""add conversion events"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260518_0002"
down_revision: str | None = "20260518_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversion_events",
        sa.Column("id", sa.INT(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BIGINT(), nullable=False),
        sa.Column("input_format", sa.VARCHAR(), nullable=False),
        sa.Column("output_format", sa.VARCHAR(), nullable=False),
        sa.Column("success", sa.BOOLEAN(), nullable=False),
        sa.Column("error_message", sa.TEXT(), nullable=True),
        sa.Column("duration_ms", sa.INT(), nullable=True),
        sa.Column("input_size_bytes", sa.BIGINT(), nullable=True),
        sa.Column("output_size_bytes", sa.BIGINT(), nullable=True),
        sa.Column("backend", sa.VARCHAR(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversion_events_backend"), "conversion_events", ["backend"])
    op.create_index(op.f("ix_conversion_events_created_at"), "conversion_events", ["created_at"])
    op.create_index(
        op.f("ix_conversion_events_input_format"), "conversion_events", ["input_format"]
    )
    op.create_index(
        op.f("ix_conversion_events_output_format"), "conversion_events", ["output_format"]
    )
    op.create_index(op.f("ix_conversion_events_success"), "conversion_events", ["success"])
    op.create_index(op.f("ix_conversion_events_user_id"), "conversion_events", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_conversion_events_user_id"), table_name="conversion_events")
    op.drop_index(op.f("ix_conversion_events_success"), table_name="conversion_events")
    op.drop_index(op.f("ix_conversion_events_output_format"), table_name="conversion_events")
    op.drop_index(op.f("ix_conversion_events_input_format"), table_name="conversion_events")
    op.drop_index(op.f("ix_conversion_events_created_at"), table_name="conversion_events")
    op.drop_index(op.f("ix_conversion_events_backend"), table_name="conversion_events")
    op.drop_table("conversion_events")
