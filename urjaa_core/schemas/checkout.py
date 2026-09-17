from decimal import Decimal
from pydantic import BaseModel, Field
from uuid import UUID


class CheckoutAddress(BaseModel):
    line1: str = Field(min_length=1)
    line2: str | None = None
    city: str = Field(min_length=1)
    state: str = Field(min_length=1)
    postal_code: str = Field(min_length=1)
    country: str = Field(min_length=1)


class CheckoutItemRequest(BaseModel):
    product_id: UUID
    variant_id: UUID
    quantity: int = Field(ge=1)


class CheckoutCreateRequest(BaseModel):
    email: str = Field(min_length=3)
    full_name: str = Field(min_length=1)
    phone: str | None = None
    shipping_address: CheckoutAddress
    items: list[CheckoutItemRequest]


class CheckoutOrderItemResponse(BaseModel):
    id: int
    store_id: UUID
    product_id: UUID
    variant_id: UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal

    class Config:
        orm_mode = True


class CheckoutOrderResponse(BaseModel):
    id: UUID
    store_id: UUID | None
    email: str
    full_name: str
    phone: str | None
    shipping_address: dict
    total_amount: Decimal
    status: str
    items: list[CheckoutOrderItemResponse]

    class Config:
        orm_mode = True


class CheckoutPaymentOrderCreateRequest(BaseModel):
    order_id: UUID


class CheckoutPaymentOrderResponse(BaseModel):
    razorpay_order_id: str
    amount_paise: int
    currency: str
    key_id: str


class CheckoutVerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class CheckoutVerifyPaymentResponse(BaseModel):
    message: str
    order_id: UUID


class CheckoutSummaryRequest(BaseModel):
    order_id: UUID


class CheckoutSummaryResponse(BaseModel):
    order_id: UUID
    subtotal: Decimal
    tax: Decimal
    grand_total: Decimal
    formatted_tax: str
    formatted_grand_total: str
