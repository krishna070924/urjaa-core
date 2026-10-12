from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

REVIEW_REPLY_MAX_LENGTH = 2000


class AdminReviewResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str
    product_slug: str | None = None
    user_id: UUID | None
    reviewer_name: str | None = None
    reviewer_email: str | None
    rating: int
    title: str | None
    content: str
    is_verified_purchase: bool
    is_approved: bool
    created_at: datetime
    moderated_at: datetime | None = None
    reply_content: str | None = None
    replied_at: datetime | None = None
    replied_by_email: str | None = None


class AdminReviewUpdateRequest(BaseModel):
    is_approved: bool


class AdminReviewReplyRequest(BaseModel):
    # Plain text: stored as typed, rendered as a text node by both frontends.
    content: str = Field(min_length=1, max_length=REVIEW_REPLY_MAX_LENGTH)


class AdminReviewCounts(BaseModel):
    visible: int
    hidden: int
    awaiting_reply: int


class PaginatedAdminReviewsResponse(BaseModel):
    items: list[AdminReviewResponse]
    page: int
    limit: int
    total: int
    pages: int
    counts: AdminReviewCounts | None = None
