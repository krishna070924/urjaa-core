from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AdminReviewResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str
    user_id: UUID | None
    reviewer_email: str | None
    rating: int
    title: str | None
    content: str
    is_verified_purchase: bool
    is_approved: bool
    created_at: datetime


class AdminReviewUpdateRequest(BaseModel):
    is_approved: bool


class PaginatedAdminReviewsResponse(BaseModel):
    items: list[AdminReviewResponse]
    page: int
    limit: int
    total: int
    pages: int
