from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewCreateRequest(BaseModel):
    product_id: UUID
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=150)
    content: str = Field(min_length=1)


class ProductReviewPublicResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str | None = None
    product_slug: str | None = None
    rating: int
    title: str | None
    content: str
    is_verified_purchase: bool
    created_at: datetime
    reviewer_name: str


class ProductReviewsResponse(BaseModel):
    average_rating: float
    total_count: int
    rating_breakdown: dict[int, int]
    items: list[ProductReviewPublicResponse]
    page: int
    limit: int
    pages: int
    sort: str


class FeaturedReviewsResponse(BaseModel):
    items: list[ProductReviewPublicResponse]
    limit: int


class ReviewCreateResponse(BaseModel):
    message: str
    review: ProductReviewPublicResponse
