import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class OrderStatus(str, enum.Enum):
    PENDING = "pending"      # winner determined, awaiting fulfilment
    CONFIRMED = "confirmed"  # kept simple on purpose - no payment gateway
    CANCELLED = "cancelled"  # e.g. auction had no bids


class Order(Base):
    """
    Created by the background worker once an auction ends with a winner.
    There is deliberately no payment integration here (out of scope) - this
    models the "who owes what for which auction" record that a real
    checkout/payment step would consume.
    """

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    auction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auctions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
    Enum(
        OrderStatus,
        name="order_status",
        values_callable=lambda enum_cls: [e.value for e in enum_cls],
    ),
    nullable=False,
    default=OrderStatus.PENDING,
)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    auction = relationship("Auction", back_populates="order")
    buyer = relationship("User")
