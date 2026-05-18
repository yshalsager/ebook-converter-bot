from datetime import UTC, datetime

from sqlalchemy import BIGINT, BOOLEAN, INT, TEXT, VARCHAR, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ebook_converter_bot.db.base import Base


class ConversionEvent(Base):
    __tablename__ = "conversion_events"

    id: Mapped[int] = mapped_column(INT(), primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(), nullable=False, index=True)
    input_format: Mapped[str] = mapped_column(VARCHAR(), nullable=False, index=True)
    output_format: Mapped[str] = mapped_column(VARCHAR(), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(BOOLEAN(), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(TEXT(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(INT(), nullable=True)
    input_size_bytes: Mapped[int | None] = mapped_column(BIGINT(), nullable=True)
    output_size_bytes: Mapped[int | None] = mapped_column(BIGINT(), nullable=True)
    backend: Mapped[str | None] = mapped_column(VARCHAR(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
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
