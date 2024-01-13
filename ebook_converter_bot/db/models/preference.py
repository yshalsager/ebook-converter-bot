from sqlalchemy import BIGINT, INT, VARCHAR, Column, ForeignKey

from ebook_converter_bot.db.base import Base


class Preference(Base):
    __tablename__ = "preferences"
    id: int = Column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: int = Column(
        BIGINT(), ForeignKey("chats.user_id"), unique=True, nullable=False
    )
    language: str = Column(VARCHAR(), nullable=False, default="en")

    def __repr__(self) -> str:
        return f"<Preference(user_id={self.user_id}, language={self.language})>"
