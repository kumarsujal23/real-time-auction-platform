import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.bid import BidCreate, BidOut
from app.services import bid_service

from app.core.rate_limit import rate_limit

router = APIRouter(prefix="/api/auctions", tags=["bids"])

@router.post("/{auction_id}/bids", response_model=BidOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit)])
async def place_bid(
    auction_id: uuid.UUID,
    payload: BidCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BidOut:
    try:
        result = await bid_service.place_bid(
            db,
            auction_id=auction_id,
            bidder=current_user,
            amount=Decimal(str(payload.amount)),
            idempotency_key=payload.idempotency_key,
        )
    except bid_service.AuctionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except bid_service.AuctionNotActiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except bid_service.SelfBidError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except bid_service.BidTooLowError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Bid too low. Minimum required: {exc.minimum_required}",
        ) from exc

    # Broadcast is now handled by the Transactional Outbox pattern asynchronously.
    
    # Invalidate Redis cache
    from app.websocket.manager import get_redis
    redis_client = get_redis()
    await redis_client.delete(f"cache:auction:{auction_id}")
    await redis_client.delete(f"cache:bids:{auction_id}")

    return BidOut(
        id=result.bid.id,
        auction_id=result.bid.auction_id,
        bidder_id=result.bid.bidder_id,
        bidder_name=current_user.full_name,
        amount=float(result.bid.amount),
        created_at=result.bid.created_at,
    )
