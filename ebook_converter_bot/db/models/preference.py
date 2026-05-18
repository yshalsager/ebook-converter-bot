from sqlalchemy import BIGINT, INT, VARCHAR, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ebook_converter_bot.db.base import Base


class Preference(Base):
    __tablename__ = "preferences"
    id: Mapped[int] = mapped_column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BIGINT(), ForeignKey("chats.user_id"), unique=True, nullable=False
    )
    language: Mapped[str] = mapped_column(VARCHAR(), nullable=False, default="en")

    def __repr__(self) -> str:
        return f"<Preference(user_id={self.user_id}, language={self.language})>"
