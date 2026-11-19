"""add payments and conversion charges"""

import sqlalchemy as sa
from alembic import op

revision = "20261118_0003"
down_revision = "20260518_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.INT(), primary_key=True),
        sa.Column("user_id", sa.BIGINT(), nullable=False),
        sa.Column("product", sa.VARCHAR(), nullable=False),
        sa.Column("kind", sa.VARCHAR(), nullable=False),
        sa.Column("stars", sa.INT(), nullable=False),
        sa.Column("credits", sa.INT(), nullable=False),
        sa.Column("charge_id", sa.VARCHAR(), nullable=False),
        sa.Column("provider_charge_id", sa.VARCHAR(), nullable=False, unique=True),
        sa.Column("subscription_until", sa.DateTime(timezone=True)),
        sa.Column("recurring", sa.BOOLEAN(), nullable=False),
        sa.Column("status", sa.VARCHAR(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.add_column(
        "conversion_events",
        sa.Column("charge", sa.VARCHAR(), nullable=False, server_default="free"),
    )
    op.add_column("conversion_events", sa.Column("payer_id", sa.BIGINT()))
    op.create_index(
        "ix_conversion_events_user_created", "conversion_events", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_conversion_events_payer_charge", "conversion_events", ["payer_id", "charge"]
    )
    op.add_column("chats", sa.Column("paywall_seen_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("chats", "paywall_seen_at")
    op.drop_index("ix_conversion_events_payer_charge", table_name="conversion_events")
    op.drop_index("ix_conversion_events_user_created", table_name="conversion_events")
    op.drop_column("conversion_events", "payer_id")
    op.drop_column("conversion_events", "charge")
    op.drop_table("payments")
