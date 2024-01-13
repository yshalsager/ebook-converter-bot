from sqlalchemy import BIGINT, INT, VARCHAR, Column

from ebook_converter_bot.db.base import Base


class Chat(Base):
    __tablename__ = "chats"
    id: int = Column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: int = Column(BIGINT(), unique=True, nullable=False)
    user_name: str = Column(VARCHAR(), nullable=False)
    type: int = Column(INT(), nullable=False)  # 0=user, 1=group, 2=channel
    usage_times: int = Column(INT(), nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Chat(user_id={self.user_id}, user_name={self.user_name})>"
