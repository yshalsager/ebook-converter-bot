from datetime import UTC, datetime

from sqlalchemy import BIGINT, BOOLEAN, INT, VARCHAR, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ebook_converter_bot.db.base import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(INT(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BIGINT(), index=True)
    product: Mapped[str] = mapped_column(VARCHAR())
    kind: Mapped[str] = mapped_column(VARCHAR())
    stars: Mapped[int] = mapped_column(INT())
    credits: Mapped[int] = mapped_column(INT())
    charge_id: Mapped[str] = mapped_column(VARCHAR())
    provider_charge_id: Mapped[str] = mapped_column(VARCHAR(), unique=True)
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurring: Mapped[bool] = mapped_column(BOOLEAN(), default=False)
    status: Mapped[str] = mapped_column(VARCHAR(), default="paid")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
