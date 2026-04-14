from datetime import UTC, datetime

from sqlalchemy import BIGINT, INT, TEXT, Column, DateTime

from ebook_converter_bot.db.base import Base


class UserOptionDefault(Base):
    __tablename__ = "user_option_defaults"

    id: int = Column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: int = Column(BIGINT(), unique=True, nullable=False, index=True)
    options_json: str = Column(TEXT(), nullable=False)
    updated_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<UserOptionDefault(user_id={self.user_id}, updated_at={self.updated_at})>"
