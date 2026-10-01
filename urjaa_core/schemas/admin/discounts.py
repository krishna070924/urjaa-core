from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

DiscountStatus = str  # "scheduled" | "active" | "expired" | "inactive"


class DiscountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # D28: percentage only, 0 < percent <= 90 (matches the DB check constraint).
    percent: Decimal = Field(gt=0, le=90)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True
    applies_to_all: bool = False
    # Ignored when applies_to_all is true; required (non-empty) otherwise.
    product_ids: list[UUID] = Field(default_factory=list)

    @field_validator("ends_at")
    @classmethod
    def _window_order(cls, ends_at, info):
        starts_at = info.data.get("starts_at")
        if ends_at is not None and starts_at is not None and ends_at <= starts_at:
            raise ValueError("ends_at must be after starts_at")
        return ends_at


class DiscountUpdateRequest(BaseModel):
    """Partial update: a field left out (None) is unchanged. Same convention
    as ProductUpdateRequest -- there is no way to clear starts_at/ends_at back
    to null via update; not needed for this ticket."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    percent: Decimal | None = Field(default=None, gt=0, le=90)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool | None = None
    applies_to_all: bool | None = None
    product_ids: list[UUID] | None = None

    @field_validator("ends_at")
    @classmethod
    def _window_order(cls, ends_at, info):
        starts_at = info.data.get("starts_at")
        if ends_at is not None and starts_at is not None and ends_at <= starts_at:
            raise ValueError("ends_at must be after starts_at")
        return ends_at


class AdminDiscountResponse(BaseModel):
    id: int
    store_id: UUID
    name: str
    percent: float
    starts_at: datetime | None
    ends_at: datetime | None
    is_active: bool
    applies_to_all: bool
    # Computed, not stored: scheduled (starts_at in the future) / active /
    # expired (ends_at in the past) / inactive (is_active = false).
    status: DiscountStatus
    product_count: int | None = None
    product_ids: list[UUID] | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class AdminDiscountListResponse(BaseModel):
    items: list[AdminDiscountResponse]
