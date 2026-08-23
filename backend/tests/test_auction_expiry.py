"""
Tests for the background worker: activation of scheduled auctions, winner
selection on expiry, and safety when multiple worker "instances" race to
finalize the same expired auction (SELECT ... FOR UPDATE SKIP LOCKED).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auction import Auction, AuctionStatus
from app.models.order import Order
from app.services import bid_service
from app.workers import auction_worker
from tests.conftest import make_user

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_scheduled_auction_activates_once_start_time_passes(pg_engine):
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with session_factory() as session:
        seller = await make_user(session, email=f"seller-{uuid.uuid4()}@test.com")
        now = datetime.now(timezone.utc)
        auction = Auction(
            seller_id=seller.id,
            title="Soon to start",
            description="",
            starting_price=10,
            current_price=10,
            min_increment=1,
            start_time=now - timedelta(seconds=1),  # already due
            end_time=now + timedelta(hours=1),
            status=AuctionStatus.SCHEDULED,
        )
        session.add(auction)
        await session.commit()
        auction_id = auction.id

    async with session_factory() as session:
        activated = await auction_worker._activate_scheduled_auctions(session)

    assert any(a.id == auction_id for a in activated)

    async with session_factory() as session:
        refreshed = await session.get(Auction, auction_id)
        assert refreshed.status == AuctionStatus.ACTIVE


@pytest.mark.asyncio
async def test_expired_auction_with_bids_gets_highest_bidder_as_winner(pg_engine):
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async with session_factory() as session:
        seller = await make_user(session, email=f"seller-{uuid.uuid4()}@test.com")
        bidder_low = await make_user(session, email=f"low-{uuid.uuid4()}@test.com")
        bidder_high = await make_user(session, email=f"high-{uuid.uuid4()}@test.com")

        now = datetime.now(timezone.utc)
        auction = Auction(
            seller_id=seller.id,
            title="Ending soon",
            description="",
            starting_price=100,
            current_price=100,
            min_increment=5,
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(seconds=1),  # about to expire
            status=AuctionStatus.ACTIVE,
        )
        session.add(auction)
        await session.commit()
        auction_id = auction.id

    async with session_factory() as session:
        await bid_service.place_bid(
            session,
            auction_id=auction_id,
            bidder=bidder_low,
            amount=Decimal("110"),
            idempotency_key="low",
        )
    async with session_factory() as session:
        await bid_service.place_bid(
            session,
            auction_id=auction_id,
            bidder=bidder_high,
            amount=Decimal("150"),
            idempotency_key="high",
        )

    await asyncio.sleep(1.2)  # let end_time pass

    async with session_factory() as session:
        finalized = await auction_worker._finalize_one_expired_auction(session)

    assert finalized is not None
    assert finalized.id == auction_id
    assert finalized.status == AuctionStatus.COMPLETED
    assert finalized.winner_id == bidder_high.id

    async with session_factory() as session:
        order = await session.scalar(select(Order).where(Order.auction_id == auction_id))
        assert order is not None
        assert order.buyer_id == bidder_high.id
        assert float(order.amount) == 150.0


@pytest.mark.asyncio
async def test_expired_auction_with_no_bids_completes_without_winner(pg_engine):
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async with session_factory() as session:
        seller = await make_user(session, email=f"seller-{uuid.uuid4()}@test.com")
        now = datetime.now(timezone.utc)
        auction = Auction(
            seller_id=seller.id,
            title="No interest",
            description="",
            starting_price=100,
            current_price=100,
            min_increment=5,
            start_time=now - timedelta(minutes=10),
            end_time=now - timedelta(seconds=1),  # already past
            status=AuctionStatus.ACTIVE,
        )
        session.add(auction)
        await session.commit()
        auction_id = auction.id

    async with session_factory() as session:
        finalized = await auction_worker._finalize_one_expired_auction(session)

    assert finalized.status == AuctionStatus.COMPLETED
    assert finalized.winner_id is None

    async with session_factory() as session:
        order = await session.scalar(select(Order).where(Order.auction_id == auction_id))
        assert order is None


@pytest.mark.asyncio
async def test_concurrent_finalization_attempts_do_not_double_process(pg_engine):
    """
    Simulates two worker instances racing to finalize the SAME expired
    auction at the same time via SELECT ... FOR UPDATE SKIP LOCKED: exactly
    one must actually process it, the other must see nothing to do (rather
    than blocking forever or double-creating an Order).
    """
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async with session_factory() as session:
        seller = await make_user(session, email=f"seller-{uuid.uuid4()}@test.com")
        now = datetime.now(timezone.utc)
        auction = Auction(
            seller_id=seller.id,
            title="Contested finalize",
            description="",
            starting_price=100,
            current_price=100,
            min_increment=5,
            start_time=now - timedelta(minutes=10),
            end_time=now - timedelta(seconds=1),
            status=AuctionStatus.ACTIVE,
        )
        session.add(auction)
        await session.commit()
        auction_id = auction.id

    async def worker_attempt():
        async with session_factory() as session:
            return await auction_worker._finalize_one_expired_auction(session)

    results = await asyncio.gather(worker_attempt(), worker_attempt())
    processed = [r for r in results if r is not None]
    assert len(processed) == 1

    async with session_factory() as session:
        order_count = len(
            (await session.execute(select(Order).where(Order.auction_id == auction_id)))
            .scalars()
            .all()
        )
    assert order_count == 0  # no bids were placed, so no order either way
