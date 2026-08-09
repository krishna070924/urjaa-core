from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WishlistAddRequest(BaseModel):
    product_id: UUID
    variant_id: UUID | None = None


class WishlistVariantResponse(BaseModel):
    id: UUID
    size: str | None
    sku_code: str | None
    stock_quantity: int


class WishlistItemResponse(BaseModel):
    product_id: UUID
    name: str
    slug: str
    price: float | None
    image: str | None
    variant: WishlistVariantResponse | None = None
    created_at: datetime


class WishlistAddResponse(BaseModel):
    item: WishlistItemResponse
