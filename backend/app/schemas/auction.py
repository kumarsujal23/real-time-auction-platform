import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from app.models.auction import AuctionStatus


class AuctionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    starting_price: float = Field(gt=0)
    min_increment: float = Field(default=1.0, gt=0)
    start_time: datetime
    end_time: datetime

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, end_time: datetime, info):
        start_time = info.data.get("start_time")
        if start_time and end_time <= start_time:
            raise ValueError("end_time must be after start_time")
        return end_time

    @field_validator("start_time", "end_time")
    @classmethod
    def must_have_tz(cls, value: datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class AuctionUpdate(BaseModel):
    """Only fields that are safe to edit before the auction goes ACTIVE."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    start_time: datetime | None = None
    end_time: datetime | None = None


class SellerOut(BaseModel):
    id: uuid.UUID
    full_name: str

    model_config = {"from_attributes": True}


class AuctionOut(BaseModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    title: str
    description: str
    starting_price: float
    current_price: float
    min_increment: float
    start_time: datetime
    end_time: datetime
    status: AuctionStatus
    winner_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuctionListOut(AuctionOut):
    bid_count: int = 0
