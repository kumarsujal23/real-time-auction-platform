"""
Fast, single-connection unit tests for the bid validation rules in
bid_service.place_bid. These don't exercise real concurrency (see
test_concurrent_bidding.py for that, against real Postgres) - they check
that each rejection path behaves correctly in isolation.
"""
from decimal import Decimal

import pytest

from app.services import bid_service
from tests.conftest import make_active_auction, make_user


@pytest.mark.asyncio
async def test_first_bid_must_clear_starting_price(sqlite_session):
    seller = await make_user(sqlite_session, email="seller@test.com")
    bidder = await make_user(sqlite_session, email="bidder@test.com")
    auction = await make_active_auction(sqlite_session, seller=seller, starting_price=100, min_increment=5)

    with pytest.raises(bid_service.BidTooLowError):
        await bid_service.place_bid(
            sqlite_session,
            auction_id=auction.id,
            bidder=bidder,
            amount=Decimal("100"),  # not >= starting_price + increment
            idempotency_key="key-1",
        )


@pytest.mark.asyncio
async def test_valid_bid_updates_current_price(sqlite_session):
    seller = await make_user(sqlite_session, email="seller2@test.com")
    bidder = await make_user(sqlite_session, email="bidder2@test.com")
    auction = await make_active_auction(sqlite_session, seller=seller, starting_price=100, min_increment=5)

    result = await bid_service.place_bid(
        sqlite_session,
        auction_id=auction.id,
        bidder=bidder,
        amount=Decimal("105"),
        idempotency_key="key-2",
    )

    assert result.was_duplicate is False
    assert float(result.auction.current_price) == 105.0


@pytest.mark.asyncio
async def test_second_bid_must_clear_increment_over_current_price(sqlite_session):
    seller = await make_user(sqlite_session, email="seller3@test.com")
    bidder_a = await make_user(sqlite_session, email="biddera3@test.com")
    bidder_b = await make_user(sqlite_session, email="bidderb3@test.com")
    auction = await make_active_auction(sqlite_session, seller=seller, starting_price=100, min_increment=5)

    await bid_service.place_bid(
        sqlite_session, auction_id=auction.id, bidder=bidder_a, amount=Decimal("105"), idempotency_key="a"
    )

    with pytest.raises(bid_service.BidTooLowError) as exc_info:
        await bid_service.place_bid(
            sqlite_session,
            auction_id=auction.id,
            bidder=bidder_b,
            amount=Decimal("108"),  # needs >= 110
            idempotency_key="b",
        )
    assert exc_info.value.minimum_required == Decimal("110")


@pytest.mark.asyncio
async def test_seller_cannot_bid_on_own_auction(sqlite_session):
    seller = await make_user(sqlite_session, email="seller4@test.com")
    auction = await make_active_auction(sqlite_session, seller=seller)

    with pytest.raises(bid_service.SelfBidError):
        await bid_service.place_bid(
            sqlite_session,
            auction_id=auction.id,
            bidder=seller,
            amount=Decimal("200"),
            idempotency_key="c",
        )


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_is_a_no_op(sqlite_session):
    seller = await make_user(sqlite_session, email="seller5@test.com")
    bidder = await make_user(sqlite_session, email="bidder5@test.com")
    auction = await make_active_auction(sqlite_session, seller=seller, starting_price=100, min_increment=5)

    first = await bid_service.place_bid(
        sqlite_session,
        auction_id=auction.id,
        bidder=bidder,
        amount=Decimal("110"),
        idempotency_key="same-key",
    )
    # Retry with the identical idempotency key (simulating a client retry
    # after e.g. a dropped response) - must return the SAME bid, not create
    # a second one or raise.
    second = await bid_service.place_bid(
        sqlite_session,
        auction_id=auction.id,
        bidder=bidder,
        amount=Decimal("110"),
        idempotency_key="same-key",
    )

    assert first.bid.id == second.bid.id
    assert second.was_duplicate is True


@pytest.mark.asyncio
async def test_bid_rejected_on_inactive_auction(sqlite_session):
    from datetime import datetime, timedelta, timezone

    from app.models.auction import Auction, AuctionStatus

    seller = await make_user(sqlite_session, email="seller6@test.com")
    bidder = await make_user(sqlite_session, email="bidder6@test.com")
    now = datetime.now(timezone.utc)
    auction = Auction(
        seller_id=seller.id,
        title="Not yet live",
        description="",
        starting_price=50,
        current_price=50,
        min_increment=1,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        status=AuctionStatus.SCHEDULED,
    )
    sqlite_session.add(auction)
    await sqlite_session.commit()
    await sqlite_session.refresh(auction)

    with pytest.raises(bid_service.AuctionNotActiveError):
        await bid_service.place_bid(
            sqlite_session,
            auction_id=auction.id,
            bidder=bidder,
            amount=Decimal("100"),
            idempotency_key="d",
        )
