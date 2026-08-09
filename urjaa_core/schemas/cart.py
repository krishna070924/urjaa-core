from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CartItemCreateRequest(BaseModel):
    product_id: UUID
    variant_id: UUID
    quantity: int = Field(default=1, ge=1)


class CartItemUpdateRequest(BaseModel):
    quantity: int = Field(ge=1)


class CartMergeItemRequest(BaseModel):
    product_id: UUID
    variant_id: UUID
    quantity: int = Field(ge=1)


class CartMergeRequest(BaseModel):
    items: list[CartMergeItemRequest] = Field(default_factory=list)


class CartItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    variant_id: UUID
    quantity: int
    product_name: str
    product_slug: str
    variant_size: str | None
    image_url: str | None
    # URJ-066: an unpriceable line (missing metal rate) reports null prices and
    # is_priced=False. Checkout for such a line is blocked with a clear message.
    unit_price: float | None
    line_total: float | None
    is_priced: bool = True


class CartResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    created_at: datetime
    items: list[CartItemResponse]
    item_count: int
    subtotal: float
    total: float
    formatted_subtotal: str
    formatted_total: str
    # URJ-066: true when at least one line cannot be priced; the storefront must
    # block checkout and prompt the shopper instead of showing a wrong total.
    has_unpriceable_items: bool = False
