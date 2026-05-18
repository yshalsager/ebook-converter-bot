from sqlalchemy import BIGINT, INT, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from ebook_converter_bot.db.base import Base


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(), unique=True, nullable=False)
    user_name: Mapped[str] = mapped_column(VARCHAR(), nullable=False)
    type: Mapped[int] = mapped_column(INT(), nullable=False)  # 0=user, 1=group, 2=channel
    usage_times: Mapped[int] = mapped_column(INT(), nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Chat(user_id={self.user_id}, user_name={self.user_name})>"
