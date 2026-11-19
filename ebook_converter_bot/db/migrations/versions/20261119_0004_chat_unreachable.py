"""mark unreachable chats instead of deleting them"""

import sqlalchemy as sa
from alembic import op

revision = "20261119_0004"
down_revision = "20261118_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chats", sa.Column("unreachable_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("chats", "unreachable_at")
