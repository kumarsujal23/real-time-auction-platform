"""
Background worker responsible for the time-driven parts of the auction
lifecycle: SCHEDULED -> ACTIVE (once start_time arrives) and
ACTIVE -> ENDED -> COMPLETED (once end_time passes), including picking the
winner and creating the resulting Order.

Design notes
------------
- Runs as a simple polling loop (`AUCTION_EXPIRY_POLL_SECONDS`, default 2s).
  A cron-like scheduler or a Postgres LISTEN/NOTIFY trigger would also
  work, but a poll loop is the simplest thing that is still correct and
  easy to reason about / test - appropriate for this project's scope.

- Safe to run MULTIPLE instances of this worker concurrently (e.g. for
  horizontal scaling or zero-downtime deploys): each poll iteration claims
  rows with `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers racing to
  process the same auction simply have one of them skip it and pick up the
  next one instead of double-processing or blocking on each other.

- Winner selection re-reads bids inside the same locked transaction that
  flips the auction to ENDED, so there's no window where a bid placed a
  moment before end_time could be missed or a bid placed after could be
  wrongly counted (the bid_service itself refuses bids once
  status != ACTIVE / now >= end_time).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.models.auction import Auction, AuctionStatus
from app.models.bid import Bid
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.services.notification_service import broadcast_auction_active, broadcast_auction_completed

logger = logging.getLogger(__name__)


async def _activate_scheduled_auctions(db: AsyncSession) -> list[Auction]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(Auction)
        .where(Auction.status == AuctionStatus.SCHEDULED, Auction.start_time <= now)
        .with_for_update(skip_locked=True)
    )
    auctions = list((await db.execute(stmt)).scalars().all())
    for auction in auctions:
        auction.status = AuctionStatus.ACTIVE
    if auctions:
        await db.commit()
        for auction in auctions:
            await db.refresh(auction)
    return auctions


async def _finalize_one_expired_auction(db: AsyncSession) -> Auction | None:
    """Claims and fully finalises at most one expired ACTIVE auction.
    Returns the finalised auction, or None if there was nothing to do."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Auction)
        .where(Auction.status == AuctionStatus.ACTIVE, Auction.end_time <= now)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    auction = await db.scalar(stmt)
    if auction is None:
        return None

    # Highest bid = winner. Ties on amount broken by earliest created_at
    # (first to bid that amount wins), which is what a real auction house
    # would do and avoids nondeterministic winner selection.
    top_bid = await db.scalar(
        select(Bid)
        .where(Bid.auction_id == auction.id)
        .order_by(Bid.amount.desc(), Bid.created_at.asc())
        .limit(1)
    )

    auction.status = AuctionStatus.ENDED

    if top_bid is not None:
        auction.winner_id = top_bid.bidder_id
        order = Order(
            auction_id=auction.id,
            buyer_id=top_bid.bidder_id,
            amount=top_bid.amount,
            status=OrderStatus.PENDING,
        )
        db.add(order)
    # else: no bids at all - auction simply completes with no winner/order.

    auction.status = AuctionStatus.COMPLETED
    await db.commit()
    await db.refresh(auction)
    return auction


async def run_once() -> None:
    """One full pass: activate anything due, finalise anything expired.
    Split into two short transactions (rather than one long one) so a slow
    winner-selection for one auction never delays activating others."""
    async with AsyncSessionLocal() as db:
        activated = await _activate_scheduled_auctions(db)
    for auction in activated:
        await broadcast_auction_active(auction)

    # Drain all currently-expired auctions this tick, one transaction each,
    # so a backlog doesn't have to wait for the next poll interval.
    while True:
        async with AsyncSessionLocal() as db:
            auction = await _finalize_one_expired_auction(db)
        if auction is None:
            break

        winner_name = None
        if auction.winner_id is not None:
            async with AsyncSessionLocal() as db:
                winner = await db.get(User, auction.winner_id)
                winner_name = winner.full_name if winner else None

        await broadcast_auction_completed(
            auction,
            winner_id=auction.winner_id,
            winner_name=winner_name,
            final_price=float(auction.current_price),
        )
        logger.info(
            "Auction %s completed. winner=%s final_price=%s",
            auction.id,
            auction.winner_id,
            auction.current_price,
        )


async def run_forever(poll_seconds: float = settings.AUCTION_EXPIRY_POLL_SECONDS) -> None:
    logger.info("Auction worker started (poll interval=%.1fs)", poll_seconds)
    while True:
        try:
            await run_once()
        except Exception:  # noqa: BLE001 - a bad tick must never kill the loop
            logger.exception("Auction worker tick failed")
        await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
