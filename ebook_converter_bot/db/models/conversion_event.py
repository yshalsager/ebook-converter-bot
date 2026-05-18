from datetime import UTC, datetime

from sqlalchemy import BIGINT, BOOLEAN, INT, TEXT, VARCHAR, Column, DateTime

from ebook_converter_bot.db.base import Base


class ConversionEvent(Base):
    __tablename__ = "conversion_events"

    id: int = Column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: int = Column(BIGINT(), nullable=False, index=True)
    input_format: str = Column(VARCHAR(), nullable=False, index=True)
    output_format: str = Column(VARCHAR(), nullable=False, index=True)
    success: bool = Column(BOOLEAN(), nullable=False, index=True)
    error_message: str | None = Column(TEXT(), nullable=True)
    duration_ms: int | None = Column(INT(), nullable=True)
    input_size_bytes: int | None = Column(BIGINT(), nullable=True)
    output_size_bytes: int | None = Column(BIGINT(), nullable=True)
    backend: str | None = Column(VARCHAR(), nullable=True)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            "<ConversionEvent("
            f"user_id={self.user_id}, input_format={self.input_format}, "
            f"output_format={self.output_format}, success={self.success})>"
        )
