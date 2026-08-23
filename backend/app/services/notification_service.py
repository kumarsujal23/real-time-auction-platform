"""
Thin formatting layer between domain events and the WebSocket manager.
Keeping the message *shape* defined in one place means the frontend has a
single contract (`type` + `payload`) to rely on regardless of which code
path triggered the event (an HTTP request handling a bid vs. the
background worker ending an auction).
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from app.models.auction import Auction
from app.models.bid import Bid
from app.websocket.manager import connection_manager

logger = logging.getLogger(__name__)


def _decimal_to_float(value) -> float:
    return float(value) if isinstance(value, Decimal) else value


async def _safe_publish(auction_id: str, message: dict) -> None:
    """
    Broadcasting is a best-effort side channel, never the source of truth:
    the bid/auction state change has ALREADY been committed to Postgres by
    the time we get here. If Redis is briefly unavailable, connected
    clients simply miss a live update (they'll see the correct state on
    their next REST fetch or reconnect) - but we must never let a
    publish failure bubble up and make an already-successful, already
    -committed request look like it failed.
    """
    try:
        await connection_manager.publish(auction_id, message)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to publish WS event for auction %s (type=%s)", auction_id, message.get("type"))


async def broadcast_new_bid(auction: Auction, bid: Bid, bidder_name: str) -> None:
    await _safe_publish(
        str(auction.id),
        {
            "type": "bid_placed",
            "payload": {
                "auction_id": str(auction.id),
                "current_price": _decimal_to_float(auction.current_price),
                "bid": {
                    "id": str(bid.id),
                    "amount": _decimal_to_float(bid.amount),
                    "bidder_name": bidder_name,
                    "created_at": bid.created_at.isoformat() if bid.created_at else None,
                },
            },
        },
    )


async def broadcast_auction_active(auction: Auction) -> None:
    await _safe_publish(
        str(auction.id),
        {
            "type": "auction_active",
            "payload": {"auction_id": str(auction.id), "status": auction.status.value},
        },
    )


async def broadcast_auction_completed(
    auction: Auction, winner_id: uuid.UUID | None, winner_name: str | None, final_price: float
) -> None:
    await _safe_publish(
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
