from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


OrderStatus = Literal["PENDING", "CONFIRMED", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"]


class OrderCreateRequest(BaseModel):
    address_id: UUID


class OrderShippingAddress(BaseModel):
    name: str | None = None
    phone: str | None = None
    line1: str = ""
    line2: str | None = None
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""


class OrderItemResponse(BaseModel):
    id: int
    store_id: UUID
    product_id: UUID
    variant_id: UUID
    product_name: str
    product_image: str | None
    quantity: int
    price: Decimal
    line_total: Decimal

    class Config:
        orm_mode = True


class OrderResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    store_id: UUID | None
    email: str
    full_name: str
    phone: str | None
    shipping_address: OrderShippingAddress
    total_amount: Decimal
    currency: str
    payment_status: str
    formatted_total: str
    status: OrderStatus
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]

    class Config:
        orm_mode = True


class PaginatedOrdersResponse(BaseModel):
    items: list[OrderResponse]
    page: int
    limit: int
    total: int
    pages: int


class AdminOrderStatusUpdateRequest(BaseModel):
    status: OrderStatus = Field(description="Next order lifecycle status")
