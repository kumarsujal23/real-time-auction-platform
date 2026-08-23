import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_optional
from app.db.database import AsyncSessionLocal, get_db
from app.models.auction import AuctionStatus
from app.models.user import User
from app.schemas.auction import AuctionCreate, AuctionListOut, AuctionOut, AuctionUpdate
from app.schemas.bid import BidOut
from app.services import auction_service
from app.services.auction_service import AuctionAuthorizationError, AuctionStateError
from app.websocket.manager import connection_manager

router = APIRouter(prefix="/api/auctions", tags=["auctions"])


@router.post("", response_model=AuctionOut, status_code=status.HTTP_201_CREATED)
async def create_auction(
    payload: AuctionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuctionOut:
    auction = await auction_service.create_auction(
        db,
        seller=current_user,
        title=payload.title,
        description=payload.description,
        starting_price=payload.starting_price,
        min_increment=payload.min_increment,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    return AuctionOut.model_validate(auction)


@router.get("", response_model=list[AuctionListOut])
async def list_auctions(
    status_filter: AuctionStatus | None = Query(default=None, alias="status"),
    mine: bool = Query(default=False, description="Only auctions created by the current user"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> list[AuctionListOut]:
    seller_id = None
    if mine:
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
        seller_id = current_user.id

    rows = await auction_service.list_auctions(
        db, status=status_filter, seller_id=seller_id, limit=limit, offset=offset
    )
    return [
        AuctionListOut(**AuctionOut.model_validate(auction).model_dump(), bid_count=bid_count)
        for auction, bid_count in rows
    ]


@router.get("/{auction_id}", response_model=AuctionOut)
async def get_auction(auction_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> AuctionOut:
    auction = await auction_service.get_auction(db, auction_id)
    if auction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
    return AuctionOut.model_validate(auction)


@router.patch("/{auction_id}", response_model=AuctionOut)
async def update_auction(
    auction_id: uuid.UUID,
    payload: AuctionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuctionOut:
    auction = await auction_service.get_auction(db, auction_id)
    if auction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
    try:
        auction = await auction_service.update_auction(
            db, auction=auction, seller_id=current_user.id, **payload.model_dump(exclude_unset=True)
        )
    except AuctionAuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AuctionStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AuctionOut.model_validate(auction)


@router.get("/{auction_id}/bids", response_model=list[BidOut])
async def get_bid_history(auction_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[BidOut]:
    auction = await auction_service.get_auction(db, auction_id)
    if auction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auction not found")
    bids = await auction_service.get_bid_history(db, auction_id)
    return [
        BidOut(
            id=bid.id,
            auction_id=bid.auction_id,
            bidder_id=bid.bidder_id,
            bidder_name=bid.bidder.full_name if bid.bidder else None,
            amount=float(bid.amount),
            created_at=bid.created_at,
        )
        for bid in bids
    ]


@router.websocket("/{auction_id}/ws")
async def auction_websocket(websocket: WebSocket, auction_id: uuid.UUID) -> None:
    """
    Live updates for a single auction. Watching an auction is public, so no
    auth is required to connect - only bid PLACEMENT (over the regular HTTP
    endpoint) requires a JWT.
    """
    await connection_manager.register(str(auction_id), websocket)
    try:
        async with AsyncSessionLocal() as db:
            auction = await auction_service.get_auction(db, auction_id)
        if auction is None:
            await websocket.send_json({"type": "error", "payload": {"detail": "Auction not found"}})
            await websocket.close(code=4404)
            return

        while True:
            # We don't expect meaningful client messages, but we must keep
            # receiving in order to detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.unregister(str(auction_id), websocket)
