from sqlalchemy import INT, VARCHAR, Column

from ebook_converter_bot.db.base import Base


class Analytics(Base):
    __tablename__ = "analytics"
    id: int = Column(INT(), primary_key=True, autoincrement=True, nullable=False)
    format: str = Column(VARCHAR(), nullable=False)
    input_times: int = Column(INT(), nullable=False, default=0)
    output_times: int = Column(INT(), nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Analytics(format={self.format}, input_times={self.input_times}, output_times={self.output_times})>"
