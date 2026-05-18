from sqlalchemy import INT, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from ebook_converter_bot.db.base import Base


class Analytics(Base):
    __tablename__ = "analytics"
    id: Mapped[int] = mapped_column(INT(), primary_key=True, autoincrement=True, nullable=False)
    format: Mapped[str] = mapped_column(VARCHAR(), nullable=False)
    input_times: Mapped[int] = mapped_column(INT(), nullable=False, default=0)
    output_times: Mapped[int] = mapped_column(INT(), nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Analytics(format={self.format}, input_times={self.input_times}, output_times={self.output_times})>"
