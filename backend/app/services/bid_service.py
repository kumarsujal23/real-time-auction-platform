"""
Bid placement service.

THE CONCURRENCY STORY (read this before touching `place_bid`)
---------------------------------------------------------------
Two buyers can submit a bid for the same auction within microseconds of
each other. A naive implementation:

    auction = SELECT * FROM auctions WHERE id = :id      # read
    if amount > auction.current_price:                   # compare
        UPDATE auctions SET current_price = amount ...    # write

is a classic check-then-act race: both requests can read the same
`current_price`, both pass the comparison, and both writes "succeed" -
whichever COMMITs last wins, even if it bid a lower amount, and the loser
never finds out their bid was actually not the highest. Two buyers could
even both believe they're currently winning.

The fix used here is pessimistic row-level locking:

    BEGIN;
    SELECT * FROM auctions WHERE id = :id FOR UPDATE;   -- blocks other
                                                          -- concurrent
                                                          -- bidders on the
                                                          -- SAME auction
    -- (re-validate status/time/amount against the just-locked row)
    INSERT INTO bids (...);
    UPDATE auctions SET current_price = :amount, version = version + 1;
    COMMIT;                                              -- lock released

`SELECT ... FOR UPDATE` takes a row-level exclusive lock, so a second
concurrent request for the *same* auction blocks at the SELECT until the
first transaction commits or rolls back. It then sees the fresh
`current_price` and is correctly rejected if it's no longer the highest.
Bids on *different* auctions are unaffected - the lock is per-row, not a
table lock - so throughput across auctions stays fully parallel.

This is the standard, safe way to serialise "read-modify-write" on a single
row in PostgreSQL, and is much simpler to reason about than optimistic
retries for a write path this hot and this correctness-sensitive (money).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction import Auction, AuctionStatus
from app.models.bid import Bid
from app.models.user import User


class BidError(Exception):
    """Base class for expected, user-facing bid failures (HTTP 4xx)."""


class AuctionNotFoundError(BidError):
    pass


class AuctionNotActiveError(BidError):
    pass


class BidTooLowError(BidError):
    def __init__(self, minimum_required: Decimal):
        self.minimum_required = minimum_required
        super().__init__(f"Bid must be at least {minimum_required}")


class SelfBidError(BidError):
    pass


def _as_aware_utc(value: datetime) -> datetime:
    """Normalizes a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass
class PlaceBidResult:
    bid: Bid
    auction: Auction
    was_duplicate: bool  # True if this call returned an already-recorded bid


async def place_bid(
    db: AsyncSession,
    *,
    auction_id: uuid.UUID,
    bidder: User,
    amount: Decimal,
    idempotency_key: str,
) -> PlaceBidResult:
    """
    Places a bid atomically. Raises a `BidError` subclass for any expected
    validation failure; callers translate those to HTTP responses.
    """
    existing = await db.scalar(
        select(Bid).where(
            Bid.auction_id == auction_id, Bid.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        auction = await db.get(Auction, auction_id)
        assert auction is not None
        return PlaceBidResult(bid=existing, auction=auction, was_duplicate=True)

    auction = await db.scalar(
        select(Auction).where(Auction.id == auction_id).with_for_update()
    )
    if auction is None:
        raise AuctionNotFoundError(f"Auction {auction_id} not found")

    now = datetime.now(timezone.utc)
    start_time = _as_aware_utc(auction.start_time)
    end_time = _as_aware_utc(auction.end_time)
    
    if auction.status != AuctionStatus.ACTIVE or not (start_time <= now < end_time):
        raise AuctionNotActiveError("Auction is not currently accepting bids")

    if auction.seller_id == bidder.id:
        raise SelfBidError("Sellers cannot bid on their own auction")

    minimum_required = Decimal(str(auction.current_price)) + Decimal(str(auction.min_increment))
    if amount < minimum_required:
        raise BidTooLowError(minimum_required)

    # ANTI-SNIPER AUTO-EXTENSION
    # If the bid is placed within the last 5 minutes, extend the auction so there are 5 mins remaining.
    if (end_time - now) < timedelta(minutes=5):
        auction.end_time = now + timedelta(minutes=5)

    bid = Bid(
        auction_id=auction.id,
        bidder_id=bidder.id,
        amount=amount,
        idempotency_key=idempotency_key,
    )
    db.add(bid)

    auction.current_price = amount
    auction.version += 1

    from app.models.outbox import OutboxEvent
    outbox_payload = {
        "type": "bid_placed",
        "payload": {
            "auction_id": str(auction.id),
            "current_price": float(auction.current_price),
            "end_time": auction.end_time.isoformat() if auction.end_time else None,
            "bid": {
                "id": str(bid.id),
                "amount": float(bid.amount),
                "bidder_name": bidder.full_name,
                "created_at": now.isoformat(),
            },
        },
    }
    db.add(OutboxEvent(topic=str(auction.id), payload=outbox_payload))

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Bid).where(
                Bid.auction_id == auction_id, Bid.idempotency_key == idempotency_key
            )
        )
        if existing is None:
            raise  # genuinely unexpected - re-raise
        auction = await db.get(Auction, auction_id)
        assert auction is not None
        return PlaceBidResult(bid=existing, auction=auction, was_duplicate=True)

    await db.refresh(bid)
    await db.refresh(auction)
    return PlaceBidResult(bid=bid, auction=auction, was_duplicate=False)
