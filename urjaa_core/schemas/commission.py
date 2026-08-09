from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


CommissionRequestStatus = Literal["pending", "approved", "rejected", "rescheduled"]


class CommissionCreateRequest(BaseModel):
    preferred_date: date
    preferred_time: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=5000)
    reference_images: list[str] = Field(default_factory=list)


class CommissionCreateResponse(BaseModel):
    message: str
    id: UUID
    status: CommissionRequestStatus


class CommissionImageUploadResponse(BaseModel):
    url: str
    public_id: str


class CommissionRequestListItem(BaseModel):
    id: UUID
    user_id: UUID | None
    user_name: str | None
    user_email: str | None
    preferred_date: date
    preferred_time: str
    final_date: date | None
    final_time: str | None
    status: CommissionRequestStatus
    admin_notes: str | None
    created_at: datetime
    updated_at: datetime | None


class CommissionRequestDetailResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    user_name: str | None
    user_email: str | None
    preferred_date: date
    preferred_time: str
    notes: str | None
    reference_images: list[str]
    status: CommissionRequestStatus
    admin_notes: str | None
    final_date: date | None
    final_time: str | None
    created_at: datetime
    updated_at: datetime | None


class CommissionAdminUpdateRequest(BaseModel):
    status: CommissionRequestStatus | None = None
    admin_notes: str | None = Field(default=None, max_length=5000)
    final_date: date | None = None
    final_time: str | None = Field(default=None, max_length=64)


class CommissionRequestsResponse(BaseModel):
    items: list[CommissionRequestListItem]


class PaginatedCommissionRequestsResponse(BaseModel):
    items: list[CommissionRequestListItem]
    page: int
    limit: int
    total: int
    pages: int
