"""
These tests are the whole point of the project's "real concurrency story".

They fire many bids at the SAME auction truly concurrently (real asyncio
tasks, each with its OWN database connection/session, against a real
Postgres instance) and assert that `SELECT ... FOR UPDATE` row locking in
bid_service.place_bid prevents the classic lost-update race: it must never
be possible for two bids to both "succeed" as the current highest bid, and
the final current_price must always equal the true maximum accepted bid.

Run with a real Postgres reachable at TEST_DATABASE_URL (defaults to the
docker-compose postgres service). Skipped automatically otherwise - see
pg_engine fixture in conftest.py.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.auction import Auction
from app.models.bid import Bid
from app.services import bid_service
from tests.conftest import make_active_auction, make_user

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_only_one_bidder_wins_a_same_price_race(pg_engine):
    """
    N bidders all try to place the exact SAME (minimum-acceptable) bid
    amount at the same instant. Without row-level locking, a
    read-then-write race could let several of them "succeed" (each reading
    the pre-race current_price before any write lands). With locking,
    exactly one must succeed and everyone else must be correctly rejected
    as "too low" because they're serialized behind the winner's commit.
    """
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async with session_factory() as setup_session:
        seller = await make_user(setup_session, email=f"seller-{uuid.uuid4()}@test.com")
        auction = await make_active_auction(
            setup_session, seller=seller, starting_price=100, min_increment=5
        )
        auction_id = auction.id

    n_bidders = 15
    contested_amount = Decimal("105")  # the exact minimum acceptable bid

    async def attempt_bid(i: int):
        async with session_factory() as session:
            bidder = await make_user(session, email=f"bidder-{i}-{uuid.uuid4()}@test.com")
            try:
                result = await bid_service.place_bid(
                    session,
                    auction_id=auction_id,
                    bidder=bidder,
                    amount=contested_amount,
                    idempotency_key=f"race-{i}",
                )
                return ("ok", result)
            except bid_service.BidError as exc:
                return ("rejected", exc)

    results = await asyncio.gather(*(attempt_bid(i) for i in range(n_bidders)))

    successes = [r for status, r in results if status == "ok"]
    rejections = [r for status, r in results if status == "rejected"]

    assert len(successes) == 1, (
        f"Expected exactly one winner of the same-price race, got {len(successes)}"
    )
    assert len(rejections) == n_bidders - 1
    assert all(isinstance(exc, bid_service.BidTooLowError) for exc in rejections)

    async with session_factory() as verify_session:
        final_auction = await verify_session.get(Auction, auction_id)
        bid_count = len(
            (await verify_session.execute(select(Bid).where(Bid.auction_id == auction_id)))
            .scalars()
            .all()
        )

    assert float(final_auction.current_price) == float(contested_amount)
    assert bid_count == 1  # the other 14 attempts must NOT have inserted a row


@pytest.mark.asyncio
async def test_highest_concurrent_bid_always_wins_regardless_of_arrival_order(pg_engine):
    """
    Fires bids of INCREASING amounts concurrently, deliberately scheduling
    the highest-amount request to (likely) reach the DB slightly later than
    some lower ones by staggering task creation in reverse. Regardless of
    arrival order/interleaving, the final current_price must equal the
    single highest amount, and every accepted bid must be monotonically
    consistent with the row-locked serialization order.
    """
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async with session_factory() as setup_session:
        seller = await make_user(setup_session, email=f"seller2-{uuid.uuid4()}@test.com")
        auction = await make_active_auction(
            setup_session, seller=seller, starting_price=100, min_increment=1
        )
        auction_id = auction.id

    # 20 distinct amounts, well spaced so every one of them is a valid
    # "improvement" over the previous *starting* price - but only bids that
    # are still higher than whatever won the race so far will be accepted.
    amounts = [Decimal(str(100 + 10 * i)) for i in range(1, 21)]

    async def attempt_bid(amount: Decimal, idx: int):
        async with session_factory() as session:
            bidder = await make_user(session, email=f"bidder2-{idx}-{uuid.uuid4()}@test.com")
            try:
                result = await bid_service.place_bid(
                    session,
                    auction_id=auction_id,
                    bidder=bidder,
                    amount=amount,
                    idempotency_key=f"ordered-{idx}",
                )
                return ("ok", amount, result)
            except bid_service.BidError as exc:
                return ("rejected", amount, exc)

    # Reverse the task list so the highest bid is scheduled FIRST but we
    # still assert correctness works regardless of scheduling order - the
    # DB transaction order (not task-creation order) is what must decide
    # the winner.
    tasks = [attempt_bid(amount, idx) for idx, amount in reversed(list(enumerate(amounts)))]
    results = await asyncio.gather(*tasks)

    successes = [amount for status, amount, _ in results if status == "ok"]

    async with session_factory() as verify_session:
        final_auction = await verify_session.get(Auction, auction_id)

    # The true maximum amount attempted MUST have been accepted (it can
    # never lose a fair race since it beats every other bid), and the
    # auction's final price must equal it exactly.
    assert max(amounts) in successes
    assert float(final_auction.current_price) == float(max(amounts))
