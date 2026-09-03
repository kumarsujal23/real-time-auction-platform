"""
Thin formatting layer between domain events and the Outbox table.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction import Auction
from app.models.bid import Bid
from app.models.outbox import OutboxEvent

logger = logging.getLogger(__name__)

def _decimal_to_float(value) -> float:
    return float(value) if isinstance(value, Decimal) else value

def _create_outbox_event(db: AsyncSession, auction_id: str, message: dict) -> None:
    db.add(OutboxEvent(topic=auction_id, payload=message))

def queue_auction_active(db: AsyncSession, auction: Auction) -> None:
    _create_outbox_event(
        db,
        str(auction.id),
        {
            "type": "auction_active",
            "payload": {"auction_id": str(auction.id), "status": auction.status.value},
        },
    )

def queue_auction_completed(
    db: AsyncSession, auction: Auction, winner_id: uuid.UUID | None, winner_name: str | None, final_price: float
) -> None:
    _create_outbox_event(
        db,
        str(auction.id),
        {
            "type": "auction_completed",
            "payload": {
                "auction_id": str(auction.id),
                "status": auction.status.value,
                "winner_id": str(winner_id) if winner_id else None,
                "winner_name": winner_name,
                "final_price": _decimal_to_float(final_price),
            },
        },
    )
