import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BidCreate(BaseModel):
    amount: float = Field(gt=0)
    # Client-generated key (e.g. a UUID created once per "click") so that a
    # retried network request (double-click, client timeout + retry, etc.)
    # can never be double-counted as two bids.
    idempotency_key: str = Field(min_length=1, max_length=255)


class BidOut(BaseModel):
    id: uuid.UUID
    auction_id: uuid.UUID
    bidder_id: uuid.UUID
    bidder_name: str | None = None
    amount: float
    created_at: datetime

    model_config = {"from_attributes": True}
