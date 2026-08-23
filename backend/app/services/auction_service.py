"""
Auction CRUD and lifecycle helpers.

Lifecycle: CREATED -> SCHEDULED -> ACTIVE -> ENDED -> COMPLETED.
- CREATED / SCHEDULED -> ACTIVE and ACTIVE -> ENDED transitions are time
  driven and performed by the background worker (see workers/auction_worker.py),
  not by user requests, so the clock is the single source of truth for
  when bidding opens/closes.
- ENDED -> COMPLETED also happens in the worker, once a winner (or "no
  winner") has been recorded and an Order created.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auction import Auction, AuctionStatus
from app.models.bid import Bid
from app.models.user import User


class AuctionAuthorizationError(Exception):
    pass


class AuctionStateError(Exception):
    pass


def _initial_status(start_time: datetime) -> AuctionStatus:
    now = datetime.now(timezone.utc)
    return AuctionStatus.ACTIVE if start_time <= now else AuctionStatus.SCHEDULED


async def create_auction(
    db: AsyncSession,
    *,
    seller: User,
    title: str,
    description: str,
    starting_price: float,
    min_increment: float,
    start_time: datetime,
    end_time: datetime,
) -> Auction:
    auction = Auction(
        seller_id=seller.id,
        title=title,
        description=description,
        starting_price=starting_price,
        current_price=starting_price,
        min_increment=min_increment,
        start_time=start_time,
        end_time=end_time,
        status=_initial_status(start_time),
    )
    db.add(auction)
    await db.commit()
    await db.refresh(auction)
    return auction


async def get_auction(db: AsyncSession, auction_id: uuid.UUID) -> Auction | None:
    return await db.scalar(select(Auction).where(Auction.id == auction_id))


async def list_auctions(
    db: AsyncSession,
    *,
    status: AuctionStatus | None = None,
    seller_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[tuple[Auction, int]]:
    """Returns (auction, bid_count) pairs, newest first."""
    bid_count_subq = (
        select(func.count(Bid.id)).where(Bid.auction_id == Auction.id).scalar_subquery()
    )
    stmt = select(Auction, bid_count_subq.label("bid_count")).order_by(Auction.created_at.desc())
    if status is not None:
        stmt = stmt.where(Auction.status == status)
    if seller_id is not None:
        stmt = stmt.where(Auction.seller_id == seller_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def update_auction(
    db: AsyncSession,
    *,
    auction: Auction,
    seller_id: uuid.UUID,
    **fields,
) -> Auction:
    if auction.seller_id != seller_id:
        raise AuctionAuthorizationError("Only the seller can edit this auction")
    if auction.status not in (AuctionStatus.CREATED, AuctionStatus.SCHEDULED):
        raise AuctionStateError("Cannot edit an auction that has already started")

    for key, value in fields.items():
        if value is not None:
            setattr(auction, key, value)

    await db.commit()
    await db.refresh(auction)
    return auction


async def get_bid_history(db: AsyncSession, auction_id: uuid.UUID, limit: int = 100) -> list[Bid]:
    stmt = (
        select(Bid)
        .where(Bid.auction_id == auction_id)
        .options(selectinload(Bid.bidder))
        .order_by(Bid.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
