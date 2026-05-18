from datetime import UTC, datetime

from sqlalchemy import BIGINT, INT, TEXT, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ebook_converter_bot.db.base import Base


class UserOptionDefault(Base):
    __tablename__ = "user_option_defaults"

    id: Mapped[int] = mapped_column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(), unique=True, nullable=False, index=True)
    options_json: Mapped[str] = mapped_column(TEXT(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<UserOptionDefault(user_id={self.user_id}, updated_at={self.updated_at})>"
