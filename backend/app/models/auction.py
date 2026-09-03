import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AuctionStatus(str, enum.Enum):
    CREATED = "created"      # row exists, not yet visible to buyers
    SCHEDULED = "scheduled"  # visible, waiting for start_time
    ACTIVE = "active"        # bidding open
    ENDED = "ended"          # end_time passed, worker is/has picked a winner
    COMPLETED = "completed"  # winner finalised, order created (or no bids)


class Auction(Base):
    __tablename__ = "auctions"
    __table_args__ = (
        Index("ix_auctions_status_endtime", "status", "end_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    starting_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # current_price is the authoritative "highest bid so far" (or starting
    # price if no bids yet). It is only ever mutated inside a row-locked
    # transaction in bid_service.place_bid — see that module for the
    # concurrency story.
    current_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    min_increment: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=1.0)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[AuctionStatus] = mapped_column(
    Enum(
        AuctionStatus,
        name="auction_status",
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    ),
    default=AuctionStatus.CREATED,
)

    winner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Optimistic-concurrency belt-and-braces on top of the row lock: every
    # successful bid bumps this. Not strictly required (SELECT FOR UPDATE
    # already serialises writers) but makes unexpected concurrent writers
    # (e.g. a future admin-edit endpoint) fail loudly instead of silently.
    version: Mapped[int] = mapped_column(nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    seller = relationship("User", back_populates="auctions", foreign_keys=[seller_id])
    winner = relationship("User", foreign_keys=[winner_id])
    bids = relationship(
        "Bid", back_populates="auction", order_by="Bid.created_at.desc()", cascade="all, delete-orphan"
    )
    order = relationship("Order", back_populates="auction", uselist=False, cascade="all, delete-orphan")
